"""Poem subtitle overlay pipeline (ffmpeg only, no ComfyUI/GPU)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from ...config import settings
from ...core.schemas import JobRecord
from ..base import ExternalPipeline, ExternalPipelineResult
from . import overlay


def _coerce_lines(raw: Any) -> list[tuple[str, float]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("lines must be a non-empty list of {text, start_s}")
    lines: list[tuple[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError("each poem line must be an object with text and start_s")
        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError("each poem line requires non-empty text")
        try:
            start = float(item.get("start_s"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"poem line start_s must be a number: {item!r}") from exc
        lines.append((text, max(0.0, start)))
    return lines


class PoemOverlayPipeline(ExternalPipeline):
    id = "poem_overlay"
    asset_kind = "productions"
    display_name = "Poem Subtitle Overlay"
    description = (
        "Burn an elegant title card and synced vertical calligraphy poem columns "
        "onto an existing video with ffmpeg. CPU only; no ComfyUI or GPU."
    )
    enabled = True
    replay_after_restart = True
    execution_lane = "ffmpeg"
    execution_lane_cooldown_sec = 0.0

    @property
    def output_labels(self) -> dict[str, str]:
        return {"video": "Video with poem subtitles"}

    async def run_external(
        self,
        job: JobRecord,
        *,
        inputs: dict[str, tuple[str, bytes]],
        cancel_event: asyncio.Event,
    ) -> ExternalPipelineResult:
        if cancel_event.is_set():
            raise asyncio.CancelledError
        source = inputs.get("video")
        if source is None:
            raise ValueError("a source video input is required")
        _filename, data = source
        if not data:
            raise ValueError("the source video is empty")

        params = job.params or {}
        title = str(params.get("title") or "").strip()
        author = str(params.get("author") or "").strip()
        if not title or not author:
            raise ValueError("title and author are required")
        lines = _coerce_lines(params.get("lines"))
        dynasty = str(params.get("dynasty") or "唐").strip() or "唐"
        seal_text = str(params.get("seal_text") or params.get("seal") or "狸").strip() or "狸"
        output_name = str(params.get("output_name") or "poem_overlay").strip() or "poem_overlay"
        if not output_name.lower().endswith(".mp4"):
            output_name = f"{output_name}.mp4"

        def _render(tmp_root: Path) -> tuple[bytes, dict[str, Any]]:
            source_path = tmp_root / "source.mp4"
            source_path.write_bytes(data)
            output_path = tmp_root / "overlay.mp4"
            meta = overlay.render_poem_overlay(
                input_path=source_path,
                output_path=output_path,
                title=title,
                author=author,
                lines=lines,
                dynasty=dynasty,
                seal_text=seal_text,
                width=params.get("width"),
                height=params.get("height"),
                calligraphy_font=(
                    params.get("calligraphy_font")
                    or settings.poem_calligraphy_font
                    or None
                ),
                serif_font=(
                    params.get("serif_font") or settings.poem_serif_font or None
                ),
                work_dir=tmp_root / "frames",
            )
            return output_path.read_bytes(), meta

        with tempfile.TemporaryDirectory(prefix="poem-overlay-job-") as tmp:
            rendered, meta = await asyncio.to_thread(_render, Path(tmp))
        if cancel_event.is_set():
            raise asyncio.CancelledError
        return ExternalPipelineResult(
            outputs={"video": (output_name, rendered)},
            params_update={"overlay": meta},
        )
