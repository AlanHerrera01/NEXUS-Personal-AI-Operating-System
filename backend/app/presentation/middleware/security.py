"""HTTP middleware: security headers, body-size limit, request rate limiting.

Two things this deliberately does *not* do.

**It does not authenticate.** There is no auth in NEXUS, so identity comes from
:mod:`app.presentation.dependencies.identity`. Rate limiting is keyed by that
single local principal, which means it bounds accidental or runaway volume, not
hostile traffic from a second party -- there is no second party to tell apart.
The limits are real, but calling them abuse prevention would overstate them.

**It does not inspect request bodies.** The body limit is enforced from
``Content-Length`` and by counting bytes as the stream is consumed downstream,
never by buffering and parsing. Parsing untrusted JSON here to apply a policy
would create a second parser with its own bugs, ahead of the real one.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.application.security.audit import SecurityAuditLog
from app.application.security.rate_limit import RateLimitExceeded, RateLimiter
from app.config.settings import Settings
from app.domain.value_objects.runtime_event_type import AuthorizationEventType
from app.presentation.dependencies.identity import LOCAL_USER_ID

logger = logging.getLogger("nexus.security.http")

#: Route class -> the settings field naming its limit. Grouping by class rather
#: than per-path means a new endpoint inherits a limit instead of forgetting one.
ROUTE_CLASSES: tuple[tuple[str, str], ...] = (
    ("/api/v1/agents", "rate_limit_agent_runs_per_minute"),
    ("/api/v1/permissions", "rate_limit_permission_requests_per_minute"),
    ("/api/v1/memory", "rate_limit_memory_search_per_minute"),
    ("/api/v1/mcp", "rate_limit_llm_per_minute"),
)

#: Applied when a path matches no class above. Not zero: an unbounded default
#: would leave documentation and health probes as free unmetered traffic.
DEFAULT_ROUTE_LIMIT = 120

#: Methods that can change state. Read-only traffic is not rate limited beyond
#: the default, because limiting GETs on the same bucket as runs would let a
#: polling client starve real work.
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Header echoing the request id, so a user-visible failure can be tied to a log
#: line without asking them to describe what they did.
REQUEST_ID_HEADER = "X-Request-ID"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Response headers that cost nothing and remove whole classes of issue."""

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if not self._settings.security_headers_enabled:
            return response

        headers = response.headers
        # ``nosniff`` stops a browser from re-interpreting a JSON or text response
        # as HTML, which turns any reflected content into script execution.
        headers.setdefault("X-Content-Type-Options", "nosniff")
        # The UI is a separate origin, so framing is never legitimate here.
        headers.setdefault("X-Frame-Options", "DENY")
        # Cross-origin isolation: prevents another site from timing or measuring
        # responses from this origin.
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        # Referrer headers would carry the path -- including ids -- off-site.
        headers.setdefault("Referrer-Policy", "no-referrer")
        # Every policy that is not explicitly granted is denied. This is the CSP
        # that matters most: it means a successful injection cannot phone home or
        # load remote code, even if every other control failed.
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        # Only the API's own media types; no plugin content at all.
        headers.setdefault(
            "X-Permitted-Cross-Domain-Policies", "none"
        )
        headers.setdefault(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
        )
        # Hide the server implementation. Not a control, but it removes a free
        # version fingerprint for anyone probing.
        headers.setdefault("Server", "nexus")
        if self._settings.hsts_enabled:
            headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={self._settings.hsts_max_age_seconds}; includeSubDomains",
            )
        return response


class BodySizeLimitMiddleware:
    """Refuse oversized requests.

    Plain ASGI rather than ``BaseHTTPMiddleware``, for a reason that cost a
    rewrite to discover: this has to read the request body *before* the route
    does, and then replay it. Subclassing ``BaseHTTPMiddleware`` cannot do that
``call_next`` hands the downstream app its own receive channel, so replacing
    ``request._receive`` either has no effect or starves the route of its body
    ("No response returned"). At this layer the ASGI ``scope`` is the only thing
    both the middleware and the route agree on, so the buffered body is installed
    there.

    Two checks, because one is not enough. ``Content-Length`` is client-supplied
    and can lie, so it only rejects early. The body is then read and measured, so
    a client that understates or omits the header still hits the ceiling.

    Buffering is normally the wrong move for a size limit -- it is the memory
    exhaustion you are trying to prevent. Here it is bounded by ``max_bytes``:
    the loop stops the instant the running total passes the limit and never
    accumulates more than that, so peak memory is the ceiling (256 KiB by
    default), not the size the client wanted to send.
    """

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET") not in _MUTATING_METHODS:
            await self.app(scope, receive, send)
            return

        declared = _header(scope, b"content-length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError:
                await _send_bad_request(send, "invalid Content-Length")
                return
            if declared_size > self._max_bytes:
                await _send_too_large(send, self._max_bytes)
                return
            if declared_size <= 0:
                await self.app(scope, receive, send)
                return
            # A declared length within the limit means the stream is never touched.
            # Not an optimisation: buffering a body only to hand the same bytes on
            # adds a copy, and it risks starving the route, for no extra protection
            # -- the bytes arriving are already bounded by the declared size.
            await self.app(scope, receive, send)
            return

        # No Content-Length: a chunked or otherwise streamed body. Here the size is
        # only knowable by reading, so the body is buffered up to the limit and
        # replayed. Chunked uploads are rare on this API, so the copy costs little.
        body, oversized = await _read_capped(receive, self._max_bytes)
        if oversized:
            await _send_too_large(send, self._max_bytes)
            return
        if not body:
            await self.app(scope, receive, send)
            return

        replayed = False

        async def receive_replay():
            nonlocal replayed
            if replayed:
                # Delegate rather than fabricating a disconnect: the downstream app
                # may call receive() a second time (Starlette checks for a client
                # disconnect while streaming), and a synthesised disconnect there
                # looks exactly like the client hanging up mid-request.
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, receive_replay, send)


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


async def _read_capped(receive, max_bytes: int) -> tuple[bytes, bool]:
    """Read until the body ends or it passes ``max_bytes``.

    Returns ``(body, oversized)``. At most ``max_bytes`` is ever held.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            # A body that never completes is not a body. Returning what arrived
            # lets the route fail on its own terms.
            break
        chunk = message.get("body", b"")
        total += len(chunk)
        if total > max_bytes:
            return (b"", True)
        if chunk:
            chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return (b"".join(chunks), False)


async def _send_too_large(send, max_bytes: int) -> None:
    body = json.dumps(
        {"detail": f"request body exceeds the {max_bytes} byte limit"}
    ).encode()
    await _send_response(send, 413, body)


async def _send_bad_request(send, detail: str) -> None:
    await _send_response(send, 400, json.dumps({"detail": detail}).encode())


async def _send_response(send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiting, keyed by the resolved principal."""

    def __init__(
        self,
        app,
        settings: Settings,
        audit: SecurityAuditLog,
        limiter: RateLimiter | None = None,
    ) -> None:
        super().__init__(app)
        self._settings = settings
        self._audit = audit
        self._limits = {
            "agent_runs": settings.rate_limit_agent_runs_per_minute,
            "llm": settings.rate_limit_llm_per_minute,
            "memory_search": settings.rate_limit_memory_search_per_minute,
            "permission_requests": settings.rate_limit_permission_requests_per_minute,
        }
        self._enabled = settings.rate_limit_enabled
        self._limiter = limiter or RateLimiter(
            window_seconds=settings.rate_limit_window_seconds,
            max_buckets=settings.rate_limit_max_buckets,
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._enabled:
            return await call_next(request)

        # Health and docs are excluded: a monitoring probe should never be the
        # thing that gets rate limited into a false outage.
        if request.url.path in ("/health", "/api/health", "/docs", "/openapi.json"):
            return await call_next(request)

        scope, limit = self._classify(request)
        if request.method not in _MUTATING_METHODS and scope == "default":
            return await call_next(request)

        started = time.monotonic()
        try:
            self._limiter.consume(scope, str(LOCAL_USER_ID), limit)
        except RateLimitExceeded as exceeded:
            self._audit.record(
                AuthorizationEventType.RATE_LIMIT_EXCEEDED,
                tool_name=scope,
                reason=str(exceeded),
                extra={"path": request.url.path, "retry_after": exceeded.retry_after},
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded"},
                headers={
                    "Retry-After": str(int(exceeded.retry_after)),
                    "X-RateLimit-Scope": scope,
                },
            )

        response = await call_next(request)
        response.headers.setdefault(
            "X-RateLimit-Remaining",
            str(int(self._limiter.remaining(scope, str(LOCAL_USER_ID), limit))),
        )
        response.headers.setdefault("X-RateLimit-Scope", scope)
        response.headers["X-Response-Time-Ms"] = str(
            int((time.monotonic() - started) * 1000)
        )
        return response

    def _classify(self, request: Request) -> tuple[str, int]:
        """Map a request onto a limit.

        Path-prefix based rather than method-based on purpose: the expensive
        operations are identified by the resource they touch, and a new route
        under one of these prefixes is limited without a code change here.
        """
        path = request.url.path
        if request.method not in _MUTATING_METHODS:
            return ("default", DEFAULT_ROUTE_LIMIT)
        for prefix, field in ROUTE_CLASSES:
            if path.startswith(prefix):
                return (prefix.strip("/").replace("/", "."), self._limits[_field_to_key(field)])
        return ("default", DEFAULT_ROUTE_LIMIT)


def _field_to_key(field: str) -> str:
    return field.removeprefix("rate_limit_").removesuffix("_per_minute")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request id, honouring one the caller supplied.

    A client-supplied id is accepted but sanitised, because it is echoed into
    logs and headers: an unfiltered value is a log-injection and header-splitting
    vector. Only characters that cannot break a log line or a header survive.
    """

    _ALLOWED = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    )
    _MAX_LEN = 64

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        clean = "".join(ch for ch in supplied if ch in self._ALLOWED)[: self._MAX_LEN]
        request_id = clean or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


__all__ = (
    "REQUEST_ID_HEADER",
    "BodySizeLimitMiddleware",
    "RateLimitMiddleware",
    "RequestIdMiddleware",
    "SecurityHeadersMiddleware",
)