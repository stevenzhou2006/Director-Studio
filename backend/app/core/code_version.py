"""Detect when the running backend is older than the code on disk.

The service runs uvicorn without ``--reload``, so an edit lands on disk while the
in-memory modules stay stale until the service restarts. This records the process
start time and reports backend source files modified after it, so the health
endpoint and the Director can warn loudly instead of silently misbehaving (the
root cause of the repeated title-card incident).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

# Captured once at import, i.e. when the process loads the app.
STARTED_AT = time.time()

_APP_ROOT = Path(__file__).resolve().parent.parent  # .../backend/app
_SKIP_DIRS = {"__pycache__", ".venv", "tests", "node_modules"}


def stale_files() -> list[str]:
    """Backend source files modified after this process started."""
    stale: list[str] = []
    for root, dirs, files in os.walk(_APP_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(root) / name
            try:
                if path.stat().st_mtime > STARTED_AT:
                    stale.append(str(path.relative_to(_APP_ROOT.parent)))
            except OSError:
                continue
    return sorted(stale)


def is_stale() -> bool:
    return bool(stale_files())


def warning_text() -> str:
    files = stale_files()
    if not files:
        return ""
    shown = ", ".join(files[:6])
    more = f" (+{len(files) - 6} more)" if len(files) > 6 else ""
    return (
        f"STALE CODE: {len(files)} backend file(s) were edited after this "
        f"service started and are NOT loaded in memory: {shown}{more}. "
        "Restart the service (`systemctl --user restart director-studio`) "
        "before trusting behavior that depends on those changes."
    )
