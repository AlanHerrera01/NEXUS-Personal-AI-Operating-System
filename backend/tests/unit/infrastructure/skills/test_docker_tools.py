from __future__ import annotations

import httpx

from app.config.settings import Settings
from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.skills.docker.tools.logs import DockerLogsTool


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "docker_socket_path": "/var/run/docker.sock",
        "docker_allowed_containers": "nexus-*-backend-1",
    }
    values.update(overrides)
    return Settings(**values)


def _context() -> ToolContext:
    return ToolContext(agent_id=EntityId.new(), agent_run_id=EntityId.new())


def _frame(payload: str, stream: int = 1) -> bytes:
    raw = payload.encode("utf-8")
    return bytes([stream, 0, 0, 0]) + len(raw).to_bytes(4, "big") + raw


async def test_docker_logs_reads_an_allowlisted_container() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            content=_frame("line one\n") + _frame("line two\n", stream=2),
        )

    settings = _settings(docker_max_log_chars=500)
    tool = DockerLogsTool(settings, transport=httpx.MockTransport(handler))

    result = await tool.execute(
        {"container": "nexus-demo-backend-1", "tail": 50, "since": "10m"},
        _context(),
    )

    assert result.success is True
    assert "line one" in result.data["content"]
    assert "line two" in result.data["content"]
    assert result.data["truncated"] is False
    assert len(seen) == 1
    assert seen[0].url.path == "/containers/nexus-demo-backend-1/logs"
    assert seen[0].url.params["tail"] == "50"
    assert seen[0].url.params["since"] == "10m"


async def test_docker_logs_refuses_a_container_outside_the_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the transport must not be reached")

    tool = DockerLogsTool(_settings(), transport=httpx.MockTransport(handler))

    result = await tool.execute({"container": "postgres"}, _context())

    assert result.success is False
    assert result.error_code == "DOCKER_CONTAINER_NOT_ALLOWED"


async def test_docker_logs_reports_an_unconfigured_allowlist() -> None:
    tool = DockerLogsTool(
        _settings(docker_allowed_containers=""),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    result = await tool.execute({"container": "nexus-demo-backend-1"}, _context())

    assert result.success is False
    assert result.error_code == "DOCKER_NOT_CONFIGURED"


async def test_docker_logs_reports_a_missing_socket() -> None:
    tool = DockerLogsTool(
        _settings(docker_socket_path="/does/not/exist/docker.sock")
    )

    result = await tool.execute({"container": "nexus-demo-backend-1"}, _context())

    assert result.success is False
    assert result.error_code == "DOCKER_NOT_CONFIGURED"
    assert "socket not found" in result.error_message


async def test_docker_logs_surfaces_engine_errors_without_the_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "No such container: nope"})

    tool = DockerLogsTool(_settings(), transport=httpx.MockTransport(handler))

    result = await tool.execute({"container": "nexus-demo-backend-1"}, _context())

    assert result.success is False
    assert result.error_code == "DOCKER_LOGS_FAILED"
    assert "No such container" in result.error_message
