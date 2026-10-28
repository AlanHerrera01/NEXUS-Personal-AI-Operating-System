"""``docker.logs``: read one allowlisted container's log tail.

The Docker socket is powerful, so this tool is not a generic API client. It
issues exactly one GET against ``/containers/{name}/logs``, refuses names that
are not in the configured allowlist, and never exposes a write endpoint or a
shell. The log stream is capped before it reaches the model.
"""

from __future__ import annotations

import fnmatch
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import Field

from app.application.security.injection import fence
from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.docker.tools.contracts import (
    SKILL_NAME,
    DockerLogsOutput,
)

MAX_TAIL = 2_000
MAX_SINCE_LENGTH = 64

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "container": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
            "description": "Exact container name from the configured allowlist",
        },
        "tail": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_TAIL,
            "description": "Number of trailing log lines",
        },
        "since": {
            "type": ["string", "null"],
            "maxLength": MAX_SINCE_LENGTH,
            "pattern": "^[0-9A-Za-z.:+-]{1,64}$",
            "description": "Optional Docker since value, such as 10m or an ISO timestamp",
        },
        "timestamps": {
            "type": "boolean",
            "description": "Include Docker timestamps on each line",
        },
    },
    "required": ["container"],
    "additionalProperties": False,
}


class DockerLogsInput(ToolInput):
    container: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
    )
    tail: int = Field(default=200, ge=1, le=MAX_TAIL)
    since: str | None = Field(
        default=None, max_length=MAX_SINCE_LENGTH, pattern=r"^[0-9A-Za-z.:+-]{1,64}$"
    )
    timestamps: bool = False


class DockerLogsTool(UseCaseTool):
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        patterns = settings.docker_allowed_container_patterns
        allowed = ", ".join(patterns) if patterns else "none configured"
        super().__init__(
            name="docker.logs",
            description=(
                "Read the tail of a container's logs through the Docker Engine "
                f"API. Allowed patterns: {allowed}. Read-only."
            ),
            skill_name=SKILL_NAME,
            input_model=DockerLogsInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            category="docker",
        )
        self.settings = settings
        self.transport = transport

    async def run(
        self, payload: DockerLogsInput, context: ToolContext
    ) -> DockerLogsOutput:
        patterns = self.settings.docker_allowed_container_patterns
        if not patterns:
            raise ToolExecutionError(
                ToolErrorCode.DOCKER_NOT_CONFIGURED,
                "docker access is not configured; set DOCKER_ALLOWED_CONTAINERS",
            )
        socket_path = self.settings.docker_socket_path.strip()
        if not socket_path:
            raise ToolExecutionError(
                ToolErrorCode.DOCKER_NOT_CONFIGURED,
                "docker access is not configured; set DOCKER_SOCKET_PATH",
            )
        if self.transport is None and not Path(socket_path).exists():
            raise ToolExecutionError(
                ToolErrorCode.DOCKER_NOT_CONFIGURED,
                f"docker socket not found at {socket_path}",
            )
        if not any(
            fnmatch.fnmatchcase(payload.container, pattern) for pattern in patterns
        ):
            raise ToolExecutionError(
                ToolErrorCode.DOCKER_CONTAINER_NOT_ALLOWED,
                f"container {payload.container!r} is not in DOCKER_ALLOWED_CONTAINERS",
            )

        tail = min(payload.tail, self.settings.docker_max_tail)
        params: dict[str, str] = {
            "stdout": "1",
            "stderr": "1",
            "tail": str(tail),
        }
        if payload.since:
            params["since"] = payload.since
        if payload.timestamps:
            params["timestamps"] = "1"

        max_bytes = max(64 * 1_024, self.settings.docker_max_log_chars * 4)
        try:
            async with self._client() as client:
                async with client.stream(
                    "GET",
                    f"/containers/{quote(payload.container, safe='')}/logs",
                    params=params,
                ) as response:
                    if response.status_code != 200:
                        body = await _read_limited(response, 4_096)
                        message = _docker_error(body[0]) or response.reason_phrase
                        raise ToolExecutionError(
                            ToolErrorCode.DOCKER_LOGS_FAILED,
                            f"Docker returned {response.status_code}: {message}",
                        )
                    raw, truncated = await _read_limited(response, max_bytes)
        except ToolExecutionError:
            raise
        except Exception as error:
            raise ToolExecutionError(
                ToolErrorCode.DOCKER_LOGS_FAILED,
                f"could not read Docker logs ({type(error).__name__})",
            ) from error

        text = _decode_stream(raw)
        if len(text) > self.settings.docker_max_log_chars:
            text = text[: self.settings.docker_max_log_chars]
            truncated = True

        return DockerLogsOutput(
            container=payload.container,
            content=fence(
                text,
                source=f"docker.logs {payload.container}",
                max_chars=self.settings.docker_max_log_chars,
            ),
            truncated=truncated,
            fetched_at=datetime.now(UTC),
        )

    def _client(self) -> httpx.AsyncClient:
        if self.transport is not None:
            return httpx.AsyncClient(
                transport=self.transport,
                base_url="http://docker",
                timeout=self.settings.docker_timeout_seconds,
            )
        transport = httpx.AsyncHTTPTransport(uds=self.settings.docker_socket_path)
        return httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=self.settings.docker_timeout_seconds,
        )


async def _read_limited(
    response: httpx.Response, limit: int
) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    async for chunk in response.aiter_bytes():
        remaining = limit - total
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            truncated = True
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), truncated


def _decode_stream(raw: bytes) -> str:
    """Decode Docker's 8-byte multiplexing headers when they are present."""
    if len(raw) >= 8 and raw[0] in (0, 1, 2) and raw[1:4] == b"\x00\x00\x00":
        output: list[bytes] = []
        offset = 0
        while offset + 8 <= len(raw):
            size = int.from_bytes(raw[offset + 4 : offset + 8], "big")
            start = offset + 8
            end = start + size
            if size < 0 or end > len(raw):
                break
            if raw[offset] in (1, 2):
                output.append(raw[start:end])
            offset = end
        if output:
            return b"".join(output).decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _docker_error(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    # Docker answers with {"message": "..."} for API errors. Keep the message,
    # not the JSON envelope, and bound it so a broken proxy cannot flood the
    # observation.
    marker = '"message"'
    if marker in text:
        start = text.find(":", text.find(marker)) + 1
        text = text[start:].strip().strip("{}").strip().strip('"')
    return text[:500]
