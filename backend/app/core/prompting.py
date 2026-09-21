"""App-wide global direction injected into every generation prompt.

Director Studio keeps one general global direction that every shot of every project
must follow (style, continuity, format, prohibitions). It is edited in the UI and
persisted beside the other application data, with an optional ``DS_GLOBAL_PROMPT``
environment default and an optional per-project override. The same text is injected
into:

- the Director's six-section H3 prompt writer;
- the Layout / reference-frame visual brief;
- every Comfy asset pipeline (actor, prop, Layout, scene);
- the final H3 submission as a format-safe backstop, so even a hand-edited or
  imported prompt still carries it.

The global text is never allowed to break the strict H3 six-section format: the
backstop prepends it before the first section header, which validation tolerates.
"""

from __future__ import annotations

import json
from pathlib import Path

GLOBAL_DIRECTION_MARKER = "GLOBAL DIRECTION"
APP_GLOBAL_PROMPT_FILENAME = "global_direction.json"


def app_global_prompt_path() -> Path:
    from ..config import settings

    return settings.data_dir / APP_GLOBAL_PROMPT_FILENAME


def load_app_global_prompt() -> str:
    """Read the persisted app-wide global direction (empty when unset)."""
    return _read_store().get("detail", "")


def load_app_global_negative() -> str:
    """Read the persisted app-wide negative direction (empty when unset)."""
    return _read_store().get("negative", "")


def save_app_global_prompt(text: str) -> str:
    """Persist the app-wide positive direction; returns its stored value."""
    return save_app_global_direction(detail=text, negative=None)["detail"]


def save_app_global_direction(
    *,
    detail: str | None = None,
    negative: str | None = None,
) -> dict[str, str]:
    """Persist the app-wide direction; omitted fields keep their current value."""
    current = _read_store()
    detail_value = (
        current.get("detail", "") if detail is None else (detail or "").strip()
    )
    negative_value = (
        current.get("negative", "") if negative is None else (negative or "").strip()
    )
    _write_store({"detail": detail_value, "negative": negative_value})
    return {"detail": detail_value, "negative": negative_value}


def _read_store() -> dict[str, str]:
    path = app_global_prompt_path()
    if not path.is_file():
        return {"detail": "", "negative": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"detail": "", "negative": ""}
    if not isinstance(data, dict):
        return {"detail": "", "negative": ""}
    return {
        "detail": str(data.get("detail") or "").strip(),
        "negative": str(data.get("negative") or "").strip(),
    }


def _write_store(payload: dict[str, str]) -> None:
    from ..config import settings

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = app_global_prompt_path()
    temp = path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp.replace(path)


def effective_global_negative(
    project_id: str | None = None,
    *,
    explicit: str | None = None,
) -> str:
    """Resolve the active global negative (app-wide persisted value only)."""
    if explicit is not None and explicit.strip():
        return explicit.strip()
    persisted = load_app_global_negative()
    if persisted:
        return persisted
    return ""



def effective_global_prompt(
    project_id: str | None = None,
    *,
    explicit: str | None = None,
) -> str:
    """Resolve the active global direction.

    Precedence: explicit value > per-project override > app-wide persisted value >
    ``DS_GLOBAL_PROMPT`` environment default.
    """
    if explicit is not None and explicit.strip():
        return explicit.strip()
    if project_id:
        try:
            from .projects.store import load_project

            project = load_project(project_id)
        except Exception:
            project = None
        if project is not None and (project.global_prompt or "").strip():
            return (project.global_prompt or "").strip()
    persisted = load_app_global_prompt()
    if persisted:
        return persisted
    from ..config import settings

    return (settings.global_prompt or "").strip()


def global_prompt_block(global_prompt: str) -> str:
    """Formatted mandatory-direction block, or empty string when unset."""
    text = (global_prompt or "").strip()
    if not text:
        return ""
    return (
        f"{GLOBAL_DIRECTION_MARKER} (applies to every shot; follow it exactly):\n"
        f"{text}"
    )


def append_global_prompt(base_prompt: str, global_prompt: str) -> str:
    """Append the global direction to a positive image prompt, de-duplicated."""
    text = (global_prompt or "").strip()
    if not text:
        return (base_prompt or "").strip()
    base = (base_prompt or "").strip()
    if _contains_direction(base, text):
        return base
    block = global_prompt_block(text)
    return f"{base}\n\n{block}" if base else block


def ensure_global_prompt_in_h3(prompt_text: str, global_prompt: str) -> str:
    """Prepend the global direction to a composed H3 prompt when missing.

    Text before the first ``subject_definitions:`` header is ignored by the H3
    validator, so prepending is format-safe. Returns the prompt unchanged when no
    direction is configured or it is already present.
    """
    text = (global_prompt or "").strip()
    if not text:
        return prompt_text
    if _contains_direction(prompt_text, text):
        return prompt_text
    block = global_prompt_block(text)
    return f"{block}\n\n{prompt_text}"


def _contains_direction(text: str, direction: str) -> bool:
    if not text or not direction:
        return False
    normalized = " ".join(text.split()).lower()
    needle = " ".join(direction.split()).lower()
    return needle in normalized
