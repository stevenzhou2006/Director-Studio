from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.schemas import JobRecord, JobStatus
from app.pipelines.poem_overlay import overlay
from app.pipelines.poem_overlay.pipeline import PoemOverlayPipeline

_FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg required")


def _make_video(path: Path, *, width: int = 576, height: int = 1024, seconds: int = 6) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x203040:s={width}x{height}:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )


def test_render_poem_overlay_produces_web_ready_h264(tmp_path: Path):
    source = tmp_path / "src.mp4"
    _make_video(source)
    output = tmp_path / "out.mp4"

    meta = overlay.render_poem_overlay(
        input_path=source,
        output_path=output,
        title="鹿柴",
        author="王维",
        dynasty="唐",
        seal_text="狸",
        lines=[("空山不见人", 1.0), ("但闻人语响", 2.5)],
    )

    assert output.is_file() and output.stat().st_size > 0
    assert meta["line_count"] == 2
    assert meta["width"] == 576 and meta["height"] == 1024
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,pix_fmt,profile",
            "-of",
            "csv=p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "yuv420p" in probe
    assert "High" in probe


def test_render_poem_overlay_requires_title_and_lines(tmp_path: Path):
    source = tmp_path / "src.mp4"
    _make_video(source, seconds=3)
    with pytest.raises(overlay.PoemOverlayError, match="title and author"):
        overlay.render_poem_overlay(
            input_path=source,
            output_path=tmp_path / "out.mp4",
            title="",
            author="",
            lines=[("x", 0.0)],
        )
    with pytest.raises(overlay.PoemOverlayError, match="at least one poem line"):
        overlay.render_poem_overlay(
            input_path=source,
            output_path=tmp_path / "out.mp4",
            title="鹿柴",
            author="王维",
            lines=[],
        )


@pytest.mark.asyncio
async def test_pipeline_run_external_returns_overlaid_video(tmp_path: Path):
    source = tmp_path / "src.mp4"
    _make_video(source)
    pipeline = PoemOverlayPipeline()
    job = JobRecord(
        id="job_overlay",
        pipeline_id="poem_overlay",
        asset_kind="productions",
        status=JobStatus.running,
        name="poem overlay: 鹿柴",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={
            "title": "鹿柴",
            "author": "王维",
            "dynasty": "唐",
            "lines": [{"text": "空山不见人", "start_s": 0.5}],
            "output_name": "luzhai",
        },
    )

    import asyncio

    result = await pipeline.run_external(
        job,
        inputs={"video": ("src.mp4", source.read_bytes())},
        cancel_event=asyncio.Event(),
    )

    assert "video" in result.outputs
    filename, data = result.outputs["video"]
    assert filename == "luzhai.mp4"
    assert len(data) > 0
    assert result.params_update["overlay"]["line_count"] == 1
    assert pipeline.output_labels["video"]


@pytest.mark.asyncio
async def test_pipeline_requires_source_video_input():
    import asyncio

    pipeline = PoemOverlayPipeline()
    job = JobRecord(
        id="job_overlay_missing",
        pipeline_id="poem_overlay",
        asset_kind="productions",
        status=JobStatus.running,
        name="x",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={"title": "t", "author": "a", "lines": [{"text": "x", "start_s": 0}]},
    )
    with pytest.raises(ValueError, match="source video input is required"):
        await pipeline.run_external(
            job,
            inputs={},
            cancel_event=asyncio.Event(),
        )
