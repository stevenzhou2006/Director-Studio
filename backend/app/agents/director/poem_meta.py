"""Poem metadata helpers on ``Shot.meta['poem']``.

The poem title/attribution is carried as structured metadata so the layout-frame
hook can composite a font-correct titled preview and the subtitle overlay can read
defaults without the Director repeating them. Stored on the untyped ``meta`` dict
so it round-trips through existing PATCH endpoints with no schema break.

Shape::

    {
      "title": "相思",
      "author": "王维",
      "dynasty": "唐",
      "seal": "狸",
      "lines": [{"text": "红豆生南国", "start_s": 1.0}, ...]
    }
"""

from __future__ import annotations

from typing import Any

POEM_META_KEY = "poem"


def get_poem(shot: Any) -> dict[str, Any]:
    meta = getattr(shot, "meta", None)
    if not isinstance(meta, dict):
        return {}
    poem = meta.get(POEM_META_KEY)
    return poem if isinstance(poem, dict) else {}


def has_poem(shot: Any) -> bool:
    poem = get_poem(shot)
    return bool(str(poem.get("title") or "").strip()) and bool(
        str(poem.get("author") or "").strip()
    )


def normalize_poem(raw: dict[str, Any]) -> dict[str, Any]:
    title = str(raw.get("title") or "").strip()
    author = str(raw.get("author") or "").strip()
    dynasty = str(raw.get("dynasty") or "唐").strip() or "唐"
    seal = str(raw.get("seal") or "狸").strip() or "狸"
    lines: list[dict[str, Any]] = []
    for item in raw.get("lines") or []:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            entry: dict[str, Any] = {"text": text}
            if item.get("start_s") is not None:
                try:
                    entry["start_s"] = round(float(item.get("start_s")), 3)
                except (TypeError, ValueError):
                    pass
            lines.append(entry)
        elif isinstance(item, str) and item.strip():
            lines.append({"text": item.strip()})
    return {"title": title, "author": author, "dynasty": dynasty, "seal": seal, "lines": lines}


def set_poem(shot: Any, poem: dict[str, Any]) -> Any:
    """Return a copy of ``shot`` with ``meta['poem']`` set to a normalized poem."""
    normalized = normalize_poem(poem)
    meta = dict(getattr(shot, "meta", None) or {})
    meta[POEM_META_KEY] = normalized
    return shot.model_copy(update={"meta": meta})
