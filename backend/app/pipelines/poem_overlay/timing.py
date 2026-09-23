"""Derive poem line start times from a shot's recitation audio via ASR.

The Director never guesses subtitle timings. This module runs the isolated
``asr_cli`` (faster-whisper) in a subprocess using an interpreter that has the
package installed, then maps each poem line to a spoken onset using segment and
pause structure rather than character matching — the recitation accent garbles
individual characters, so matching by glyph is unreliable.

Strategy (most → least trusted):
  1. If ASR segments line up 1:1 with the lines, use each segment's start.
  2. Otherwise group words into phrases split on pauses >= ``pause_threshold`` and
     use the phrase onsets.
  3. If the phrase count still differs from the line count, keep the matched onsets
     and interpolate the remainder across the remaining speech span so the result
     is always exactly ``len(lines)`` monotonically non-decreasing starts.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ...config import settings


class PoemTimingError(ValueError):
    """Raised when line timings cannot be derived."""


def resolve_recitation_audio(shot: Any) -> tuple[Path, float]:
    """Resolve the shot's recitation audio file and its lead-silence offset.

    Prefers the H3 mouth-sync (padded) take when present so whisper times line up
    with the video timeline. Returns ``(audio_path, lead_silence_s)``.
    """
    from ...core.library.store import asset_dir, load_asset

    refs = sorted(shot.voice_refs or [], key=lambda r: r.audio_index)
    if not refs:
        raise PoemTimingError("shot has no voice references to time against")

    for ref in refs:
        asset = load_asset("voices", ref.asset_id)
        if asset is None or not asset.files:
            continue
        meta = asset.meta or {}
        h3_key = str(meta.get("h3_file_key") or "").strip()
        candidates: list[str] = []
        if h3_key and asset.files.get(h3_key):
            candidates.append(h3_key)
        for key in ("audio_padded", ref.file_key, "audio"):
            if key and asset.files.get(key) and key not in candidates:
                candidates.append(key)
        for key in candidates:
            path = (
                asset_dir("voices", ref.asset_id, project_id=asset.project_id)
                / str(asset.files[key])
            )
            if path.is_file():
                lead = 0.0
                if key in ("audio_padded", h3_key):
                    try:
                        lead = float(meta.get("lead_silence_s") or 0.0)
                    except (TypeError, ValueError):
                        lead = 0.0
                return path, lead
    raise PoemTimingError("no readable recitation audio found for this shot")


def transcribe_words(
    audio_path: Path,
    *,
    model: str | None = None,
    language: str | None = None,
    cache_dir: str | None = None,
) -> dict[str, list[dict[str, float]]]:
    """Run the isolated ASR CLI and return ``{"words": [...], "segments": [...]}``.

    ``segments`` is best-effort; older CLIs may emit only ``words``.
    """
    cli = Path(__file__).with_name("asr_cli.py")
    if not cli.is_file():
        raise PoemTimingError(f"ASR CLI not found: {cli}")
    cmd = [
        settings.poem_asr_python,
        str(cli),
        "--in",
        str(audio_path),
        "--model",
        model or settings.poem_asr_model,
        "--language",
        language or settings.poem_asr_language,
    ]
    cache = cache_dir or settings.poem_asr_cache_dir
    if cache:
        cmd += ["--cache", cache]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.poem_asr_timeout_sec,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PoemTimingError(
            f"ASR interpreter not found: {settings.poem_asr_python}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PoemTimingError("ASR timed out") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise PoemTimingError(
            f"ASR failed (rc={result.returncode}): {result.stderr.strip()[-400:]}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PoemTimingError("ASR returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise PoemTimingError("ASR payload was not an object")
    return payload


def _phrase_starts(
    words: list[dict[str, Any]], pause_threshold: float
) -> list[float]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: float(w.get("start", 0.0)))
    starts = [float(ordered[0].get("start", 0.0))]
    prev_end = float(ordered[0].get("end", 0.0))
    for word in ordered[1:]:
        start = float(word.get("start", 0.0))
        if start - prev_end >= pause_threshold:
            starts.append(start)
        prev_end = max(prev_end, start, float(word.get("end", 0.0)))
    return starts


def derive_line_starts(
    lines: list[str],
    *,
    audio_path: Path | None = None,
    shot: Any = None,
    model: str | None = None,
    pause_threshold: float = 0.35,
) -> list[float]:
    """Return exactly ``len(lines)`` monotonic start seconds for the recitation.

    Provide either ``audio_path`` directly or a ``shot`` whose bound recitation
    audio is resolved automatically.
    """
    clean = [str(line).strip() for line in lines if str(line).strip()]
    if len(clean) != len(lines):
        raise PoemTimingError("blank poem lines are not allowed")
    if not clean:
        return []

    if audio_path is None:
        if shot is None:
            raise PoemTimingError("provide audio_path or a shot with voice refs")
        audio_path, _lead = resolve_recitation_audio(shot)

    payload = transcribe_words(Path(audio_path), model=model)
    words = payload.get("words") or []
    segments = payload.get("segments") or []
    if not words and not segments:
        raise PoemTimingError("ASR produced no speech to align lines to")

    count = len(clean)

    # 1. Segment-aligned (1:1).
    if len(segments) == count:
        return [round(float(seg.get("start", 0.0)), 2) for seg in segments]

    # 2. Pause-grouped word phrases.
    starts = _phrase_starts(words, pause_threshold)
    if len(starts) == count:
        return [round(value, 2) for value in starts]

    if len(starts) > count:
        # Keep the first (count - 1) onsets; the last line starts at the count-th
        # phrase so trailing chatter collapses into the final line.
        trimmed = starts[: count - 1] + [starts[count - 1]] if count > 1 else [starts[0]]
        return [round(value, 2) for value in trimmed]

    # 3. Fewer onsets than lines: interpolate the remainder across the tail.
    total_end = max(
        (float(w.get("end", 0.0)) for w in words),
        default=float(starts[-1] if starts else 0.0),
    )
    result = list(starts)
    base = result[-1] if result else 0.0
    remaining = count - len(result)
    span = max(0.0, total_end - base)
    step = span / (remaining + 1)
    for index in range(remaining):
        result.append(round(base + step * (index + 1), 2))
    return [round(value, 2) for value in result]
