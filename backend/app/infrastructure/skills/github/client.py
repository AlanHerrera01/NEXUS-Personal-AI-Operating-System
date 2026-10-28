"""Bounded GitHub REST calls. No retries for writes with ambiguous outcomes."""
from __future__ import annotations

import re
import ssl
from typing import Any

import httpx

from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings, get_settings
from app.domain.ports.tool import ToolContext

REPOSITORY_PATTERN = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
OWNER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$"


class GitHubClient:
    def __init__(self, settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings or get_settings()
        self.transport = transport

    def repository(self, explicit: str | None) -> str:
        repository = explicit or self.settings.github_default_repository
        if not re.fullmatch(REPOSITORY_PATTERN, repository) or any(part in {".", ".."} for part in repository.split("/")):
            raise ToolExecutionError("GITHUB_REPOSITORY_REQUIRED", "Specify repository as owner/repo or configure GITHUB_DEFAULT_REPOSITORY.")
        return repository

    async def request(self, method: str, path: str, context: ToolContext, *, payload: dict | None = None, params: dict | None = None) -> Any:
        if context.user_id is None:
            raise ToolExecutionError("GITHUB_IDENTITY_REQUIRED", "An authenticated operator is required.")
        token = self.settings.github_personal_access_token
        # Public reads do not need a GitHub token. /user is account-specific;
        # never silently turn it into a query for an invented public identity.
        if not token and (method.upper() != "GET" or path == "/user" or path.startswith("/user/")):
            raise ToolExecutionError("GITHUB_NOT_CONFIGURED", "Configure GITHUB_PERSONAL_ACCESS_TOKEN for account-specific reads or writes; public reads only need an explicit user, org or repository.")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(
                base_url="https://api.github.com",
                timeout=self.settings.github_timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
                # Include OS trust roots (notably on Windows/corporate networks)
                # while retaining hostname and certificate verification.
                verify=ssl.create_default_context(),
                headers=headers,
            ) as client:
                async with client.stream(method, path, json=payload, params=params) as response:
                    if response.status_code >= 300:
                        if response.status_code == 429 or (response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0"):
                            raise ToolExecutionError("GITHUB_RATE_LIMITED", "GitHub rate limit reached. Wait before retrying or configure a token for a higher public-read limit.")
                        # Never reflect provider content, headers or credentials into a prompt.
                        raise ToolExecutionError("GITHUB_API_ERROR", f"GitHub returned HTTP {response.status_code}. Check token permissions and repository.")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2_097_152:
                            raise ToolExecutionError("GITHUB_RESPONSE_TOO_LARGE", "GitHub response exceeded the size limit.")
            import json
            return json.loads(body)
        except httpx.HTTPError as error:
            raise ToolExecutionError("GITHUB_UNAVAILABLE", "GitHub request failed. A write may have succeeded; verify GitHub before retrying.") from error
        except (ValueError, KeyError, TypeError) as error:
            raise ToolExecutionError("GITHUB_INVALID_RESPONSE", "GitHub returned an invalid response.") from error
