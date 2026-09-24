from __future__ import annotations

import httpx
import pytest

from app.agents.director.tool_handlers import search as search_handler
from app.agents.director.tool_handlers.search import handle_search_tool
from app.agents.director.tool_schema import director_tool_schemas
from app.config import settings
from app.core.projects.store import create_project
from app.integrations.brave_search import (
    BraveSearchClient,
    BraveSearchError,
    BraveSearchResult,
)


def _brave_payload() -> dict:
    return {
        "type": "search",
        "query": {"original": "li bai jing ye si"},
        "web": {
            "type": "search",
            "total_results": 1000,
            "results": [
                {
                    "title": "静夜思 - 维基百科",
                    "url": "https://example.org/jingyesi",
                    "description": "《静夜思》是唐代李白的诗。",
                    "age": "2 days ago",
                    "extra_snippets": [
                        "床前明月光，疑是地上霜。",
                        "举头望明月，低头思故乡。",
                    ],
                },
                {
                    "title": "Li Bai - Poetry Foundation",
                    "url": "https://example.com/libai",
                    "description": "Li Bai (701-762) was a Tang dynasty poet.",
                },
            ],
        },
    }


@pytest.mark.asyncio
async def test_client_parses_web_results_and_sends_auth():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("x-subscription-token") or ""
        seen["accept"] = request.headers.get("accept") or ""
        return httpx.Response(200, json=_brave_payload())

    client = BraveSearchClient(
        api_key="secret-key",
        transport=httpx.MockTransport(handler),
    )
    results = await client.search("li bai jing ye si", count=5, search_lang="zh-hans")

    assert seen["auth"] == "secret-key"
    assert seen["accept"] == "application/json"
    assert "q=li+bai+jing+ye+si" in seen["url"]
    assert "search_lang=zh-hans" in seen["url"]
    assert len(results) == 2
    assert results[0].title.startswith("静夜思")
    assert results[0].url == "https://example.org/jingyesi"
    assert results[0].age == "2 days ago"
    assert results[0].snippets[0].startswith("床前明月光")
    assert results[1].snippets == ()


@pytest.mark.asyncio
async def test_client_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", None)
    client = BraveSearchClient(
        api_key="",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    with pytest.raises(BraveSearchError):
        await client.search("anything")


@pytest.mark.asyncio
async def test_client_raises_on_auth_error():
    client = BraveSearchClient(
        api_key="bad",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"error": "unauthorized"})
        ),
    )
    with pytest.raises(BraveSearchError) as exc:
        await client.search("x")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_client_rate_limit_is_retryable():
    client = BraveSearchClient(
        api_key="k",
        transport=httpx.MockTransport(lambda r: httpx.Response(429, json={})),
    )
    with pytest.raises(BraveSearchError) as exc:
        await client.search("x")
    assert exc.value.status_code == 429
    assert exc.value.retryable is True


@pytest.mark.asyncio
async def test_client_empty_results_returns_empty_list():
    client = BraveSearchClient(
        api_key="k",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"web": {"results": []}})
        ),
    )
    assert await client.search("nothing") == []


class _FakeClient:
    def __init__(self, results=None, error=None):
        self._results = results or []
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    async def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if self._error:
            raise self._error
        return self._results


@pytest.mark.asyncio
async def test_handler_returns_results_notes_and_payload(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", "k")
    results = [
        BraveSearchResult(
            title="T1",
            url="https://a",
            description="D1",
            snippets=("S1",),
            age="1 day ago",
        ),
        BraveSearchResult(
            title="T2",
            url="https://b",
            description="D2",
            snippets=(),
            age="",
        ),
    ]
    fake = _FakeClient(results=results)
    monkeypatch.setattr(search_handler, "BraveSearchClient", lambda *a, **k: fake)

    notes: list[str] = []
    payloads: list[dict] = []
    actions: list[str] = []
    handled = await handle_search_tool(
        name="web_search",
        args={"query": "jing ye si", "count": 2},
        project_id="p",
        actions=actions,
        notes=notes,
        result_payloads=payloads,
    )

    assert handled is True
    assert payloads[0]["ok"] is True
    assert payloads[0]["query"] == "jing ye si"
    assert len(payloads[0]["results"]) == 2
    assert payloads[0]["results"][0]["url"] == "https://a"
    assert any("T1" in note for note in notes)
    assert any("https://a" in note for note in notes)
    assert actions and actions[0].startswith("web_search:")
    assert fake.calls[0][1]["count"] == 2


@pytest.mark.asyncio
async def test_handler_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", None)
    notes: list[str] = []
    payloads: list[dict] = []
    handled = await handle_search_tool(
        name="web_search",
        args={"query": "x"},
        project_id="p",
        actions=[],
        notes=notes,
        result_payloads=payloads,
    )
    assert handled is True
    assert payloads[0]["ok"] is False
    assert "DS_BRAVE_API_KEY" in payloads[0]["error"]


@pytest.mark.asyncio
async def test_handler_requires_query(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", "k")
    with pytest.raises(ValueError):
        await handle_search_tool(
            name="web_search",
            args={},
            project_id="p",
            actions=[],
            notes=[],
            result_payloads=[],
        )


@pytest.mark.asyncio
async def test_handler_rejects_bad_freshness(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", "k")
    with pytest.raises(ValueError):
        await handle_search_tool(
            name="web_search",
            args={"query": "x", "freshness": "century"},
            project_id="p",
            actions=[],
            notes=[],
            result_payloads=[],
        )


@pytest.mark.asyncio
async def test_handler_surfaces_search_error(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", "k")
    fake = _FakeClient(error=BraveSearchError("boom", status_code=500))
    monkeypatch.setattr(search_handler, "BraveSearchClient", lambda *a, **k: fake)
    notes: list[str] = []
    payloads: list[dict] = []
    handled = await handle_search_tool(
        name="web_search",
        args={"query": "x"},
        project_id="p",
        actions=[],
        notes=notes,
        result_payloads=payloads,
    )
    assert handled is True
    assert payloads[0]["ok"] is False
    assert "boom" in payloads[0]["error"]


@pytest.mark.asyncio
async def test_handler_ignores_other_tool_names():
    handled = await handle_search_tool(
        name="get_status",
        args={},
        project_id="p",
        actions=[],
        notes=[],
        result_payloads=[],
    )
    assert handled is False


def test_web_search_offered_when_configured(tmp_projects_dir, monkeypatch):
    project = create_project("Grounded", "A door opens.")
    monkeypatch.setattr(settings, "brave_api_key", "k")
    names = {
        tool["function"]["name"]
        for tool in director_tool_schemas(
            project, current_message="写一个关于真实历史事件的剧本"
        )
    }
    assert "web_search" in names


def test_web_search_absent_when_not_configured(tmp_projects_dir, monkeypatch):
    project = create_project("Offline", "A door opens.")
    monkeypatch.setattr(settings, "brave_api_key", None)
    names = {
        tool["function"]["name"]
        for tool in director_tool_schemas(project, current_message="写一个剧本")
    }
    assert "web_search" not in names


def test_web_search_offered_with_actor_design(tmp_projects_dir, monkeypatch):
    project = create_project("Actor + search", "A detective enters.")
    monkeypatch.setattr(settings, "brave_api_key", "k")
    names = {
        tool["function"]["name"]
        for tool in director_tool_schemas(
            project,
            current_message="用 GPT 生成人物设定，四十岁的女侦探，黑色风衣",
        )
    }
    assert names == {"queue_actor_design", "web_search"}


def test_web_search_survives_shot_layout_turn(tmp_projects_dir, monkeypatch):
    project = create_project("Layout turn", "beat")
    monkeypatch.setattr(settings, "brave_api_key", "k")
    names = {
        tool["function"]["name"]
        for tool in director_tool_schemas(project, current_message="第3镜的参考帧")
    }
    assert "web_search" in names
    assert "queue_ref_frame" in names
