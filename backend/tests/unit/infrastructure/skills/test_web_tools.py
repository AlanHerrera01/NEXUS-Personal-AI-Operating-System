import json

import httpx

from app.application.security.injection import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.web.skill import WebSkill
from app.infrastructure.skills.web.tools.fetch import WebFetchTool
from app.infrastructure.skills.web.tools.search import WebSearchTool

PUBLIC_ADDRESS = "93.184.216.34"


def context() -> ToolContext:
    return ToolContext(agent_id=EntityId.new(), agent_run_id=EntityId.new())


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


async def public_resolver(host: str, port: int) -> tuple[str, ...]:
    return (PUBLIC_ADDRESS,)


def test_skill_exposes_two_read_only_tools() -> None:
    skill = WebSkill(settings())

    definitions = {tool.definition().name: tool.definition() for tool in skill.tools()}

    assert set(definitions) == {"web.search", "web.fetch"}
    assert skill.definition().name == "web"
    for definition in definitions.values():
        assert definition.skill_name == "web"
        assert definition.read_only is True
        assert definition.side_effect is False
        assert definition.requires_confirmation is False
        assert definition.risk_level is RiskLevel.LOW
        assert definition.input_schema["additionalProperties"] is False


async def test_brave_search_parses_results_and_sends_the_key() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("x-subscription-token", "")
        seen["query"] = request.url.params.get("q", "")
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Model Context Protocol",
                            "url": "https://modelcontextprotocol.io",
                            "description": "An open protocol for tools.",
                        },
                        {
                            "title": "Specification",
                            "url": "https://spec.modelcontextprotocol.io",
                            "description": "The specification.",
                        },
                    ]
                }
            },
        )

    tool = WebSearchTool(
        settings(web_search_provider="brave", web_search_api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute({"query": "mcp", "limit": 1}, context())

    assert result.success is True
    assert result.data["provider"] == "brave"
    assert result.data["count"] == 1
    assert result.data["items"][0]["title"] == "Model Context Protocol"
    assert seen == {"token": "test-key", "query": "mcp"}


async def test_duckduckgo_search_parses_and_unwraps_result_links() -> None:
    body = """
    <html><body>
      <div class="result results_links">
        <a rel="nofollow" class="result__a"
           href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&amp;rut=abc">
          Example <b>Page</b>
        </a>
        <a class="result__snippet" href="https://example.com/page">A <b>snippet</b> here.</a>
      </div>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, text=body
        )

    tool = WebSearchTool(
        settings(web_search_provider="duckduckgo"),
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute({"query": "example"}, context())

    assert result.success is True
    assert result.data["provider"] == "duckduckgo"
    assert result.data["items"] == [
        {
            "title": "Example Page",
            "url": "https://example.com/page",
            "snippet": "A snippet here.",
        }
    ]


async def test_auto_search_falls_back_to_duckduckgo_without_a_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text='<a class="result__a" href="https://example.com">Example</a>',
        )

    tool = WebSearchTool(settings(web_search_provider="auto"), transport=httpx.MockTransport(handler))

    result = await tool.execute({"query": "example"}, context())

    assert result.success is True
    assert result.data["provider"] == "duckduckgo"


async def test_duckduckgo_anti_bot_page_is_reported_not_treated_as_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text='<form id="challenge-form"><div class="anomaly-modal"></div></form>',
        )

    tool = WebSearchTool(
        settings(web_search_provider="duckduckgo"),
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute({"query": "example"}, context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.WEB_SEARCH_FAILED
    assert "anti-bot" in result.error_message


async def test_brave_rejection_is_reported_without_leaking_the_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key", "secret": "do-not-copy"})

    tool = WebSearchTool(
        settings(web_search_provider="brave", web_search_api_key="bad-key"),
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute({"query": "example"}, context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.WEB_SEARCH_FAILED
    assert "API key" in result.error_message
    assert "do-not-copy" not in result.error_message


async def test_fetch_extracts_html_and_fences_untrusted_text() -> None:
    body = """
    <html><head><title>Demo page</title></head><body>
      <script>alert("not prose")</script>
      <style>.x { color: red; }</style>
      <h1>Hello</h1><p>World</p>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, text=body
        )

    tool = WebFetchTool(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
    )

    result = await tool.execute({"url": "https://example.com/"}, context())

    assert result.success is True
    assert result.data["title"] == "Demo page"
    assert "Hello" in result.data["content"]
    assert "World" in result.data["content"]
    assert "alert" not in result.data["content"]
    assert result.data["content"].startswith(UNTRUSTED_OPEN)
    assert result.data["content"].endswith(UNTRUSTED_CLOSE)
    # The observation must fit the model's per-tool budget with the fence on.
    assert len(json.dumps(result.data)) < 2_000


async def test_fetch_truncates_to_the_requested_excerpt() -> None:
    body = "<html><body><p>" + ("x" * 5_000) + "</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, text=body
        )

    tool = WebFetchTool(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
    )

    result = await tool.execute(
        {"url": "https://example.com/", "max_chars": 300}, context()
    )

    assert result.success is True
    assert result.data["truncated"] is True
    assert "chars=300" in result.data["content"]
    assert "x" * 300 in result.data["content"]
    assert "x" * 301 not in result.data["content"]


async def test_fetch_refuses_a_hostname_that_resolves_to_loopback() -> None:
    async def loopback_resolver(host: str, port: int) -> tuple[str, ...]:
        return ("127.0.0.1",)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("the tool must not make a request")

    tool = WebFetchTool(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=loopback_resolver,
    )

    result = await tool.execute({"url": "https://localtest.me/"}, context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.WEB_URL_BLOCKED
    assert "non-public" in result.error_message


async def test_fetch_revalidates_redirects_and_blocks_an_internal_hop() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            302, headers={"location": "https://internal.example/secret"}
        )

    async def resolver(host: str, port: int) -> tuple[str, ...]:
        if host == "internal.example":
            return ("10.0.0.5",)
        return (PUBLIC_ADDRESS,)

    tool = WebFetchTool(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
    )

    result = await tool.execute({"url": "https://public.example/start"}, context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.WEB_URL_BLOCKED
    assert calls == ["https://public.example/start"]


async def test_fetch_follows_a_public_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Final</title></head><body>Landed</body></html>",
        )

    tool = WebFetchTool(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
    )

    result = await tool.execute({"url": "https://example.com/start"}, context())

    assert result.success is True
    assert result.data["url"] == "https://example.com/final"
    assert result.data["title"] == "Final"


async def test_fetch_refuses_unsupported_binary_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.7\n...",
        )

    tool = WebFetchTool(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
    )

    result = await tool.execute({"url": "https://example.com/file.pdf"}, context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.WEB_CONTENT_UNSUPPORTED
    assert "application/pdf" in result.error_message


async def test_fetch_refuses_ports_outside_the_web_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("the tool must not make a request")

    tool = WebFetchTool(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
    )

    result = await tool.execute({"url": "https://example.com:1234/"}, context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.WEB_URL_BLOCKED
    assert "port" in result.error_message


async def test_fetch_refuses_a_malformed_url_cleanly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("the tool must not make a request")

    tool = WebFetchTool(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
    )

    result = await tool.execute({"url": "http://[::1"}, context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.WEB_URL_BLOCKED
    assert "malformed" in result.error_message


async def test_fetch_enforces_the_byte_ceiling() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"a" * 5_000,
        )

    tool = WebFetchTool(
        settings(web_fetch_max_bytes=1_024, web_fetch_max_chars=20_000),
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
    )

    result = await tool.execute({"url": "https://example.com/"}, context())

    assert result.success is True
    assert result.data["truncated"] is True
    assert "chars=1024" in result.data["content"]
    assert "a" * 1_024 in result.data["content"]
    assert "a" * 1_025 not in result.data["content"]
