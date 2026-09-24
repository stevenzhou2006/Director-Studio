"""Web search tool: grounds the Director agent with current, factual, real-world info."""

from __future__ import annotations

from typing import Any

from ....config import settings
from ....integrations.brave_search import BraveSearchClient, BraveSearchError

_SEARCH_TOOL_NAMES = frozenset({"web_search", "search_web", "search"})
_VALID_FRESHNESS = frozenset({"pd", "pw", "pm", "py"})


async def handle_search_tool(
    *,
    name: str,
    args: dict[str, Any],
    project_id: str,
    actions: list[str],
    notes: list[str],
    result_payloads: list[dict[str, Any]] | None,
) -> bool:
    if name not in _SEARCH_TOOL_NAMES:
        return False

    if not settings.web_search_configured:
        message = (
            "Web search is not configured. Set DS_BRAVE_API_KEY to enable it."
        )
        if result_payloads is not None:
            result_payloads.append({"ok": False, "error": message})
        notes.append(message)
        return True

    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("web_search requires a query")

    try:
        count = int(args.get("count") or settings.brave_search_default_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("count must be an integer") from exc
    count = max(1, min(count, settings.brave_search_max_results))

    freshness = str(args.get("freshness") or "").strip().lower() or None
    if freshness is not None and freshness not in _VALID_FRESHNESS:
        raise ValueError("freshness must be one of pd, pw, pm, py")

    search_lang = str(args.get("search_lang") or "").strip().lower() or None
    country = str(args.get("country") or "").strip().lower() or None

    client = BraveSearchClient()
    try:
        results = await client.search(
            query,
            count=count,
            freshness=freshness,
            search_lang=search_lang,
            country=country,
        )
    except BraveSearchError as exc:
        if result_payloads is not None:
            result_payloads.append({"ok": False, "error": str(exc)})
        notes.append(f"web_search failed: {exc}")
        return True

    actions.append(f"web_search:{query[:60]}")

    if not results:
        if result_payloads is not None:
            result_payloads.append({"ok": True, "query": query, "results": []})
        notes.append(f"web_search for {query!r} returned no results.")
        return True

    if result_payloads is not None:
        result_payloads.append(
            {
                "ok": True,
                "query": query,
                "results": [result.as_dict() for result in results],
            }
        )

    lines = [f"Web search for {query!r}:"]
    for index, result in enumerate(results, start=1):
        age = f" ({result.age})" if result.age else ""
        lines.append(f"{index}. {result.title}{age} — {result.url}")
        detail = result.description or (result.snippets[0] if result.snippets else "")
        if detail:
            lines.append(f"   {detail}")
    notes.extend(lines)
    return True
