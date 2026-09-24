from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.agents.director import poem_meta
from app.agents.director.tool_handlers.audio import handle_audio_tool
from app.core.projects.models import Shot, ShotStatus
from app.core.projects.store import create_project, load_shot
from app.core.schemas import JobRecord, JobStatus
from app.pipelines.poem_overlay import timing
from app.pipelines.poem_overlay.overlay import render_poem_title_still
from app.pipelines.ref_frame.pipeline import RefFramePipeline


def _make_png(path: Path, *, width: int = 1728, height: int = 960) -> None:
    Image.new("RGB", (width, height), (210, 225, 235)).save(path)


def test_render_poem_title_still_composites_card(tmp_path: Path):
    src = tmp_path / "layout.png"
    out = tmp_path / "layout_titled.png"
    _make_png(src)

    meta = render_poem_title_still(
        input_path=src,
        output_path=out,
        title="相思",
        author="王维",
        dynasty="唐",
        seal_text="狸",
    )

    assert out.is_file() and out.stat().st_size > 0
    assert meta["width"] == 1728 and meta["height"] == 960
    # The composite must differ from the blank source (ink was drawn).
    base = Image.open(src).convert("RGB")
    titled = Image.open(out).convert("RGB")
    assert base.size == titled.size
    assert list(base.getdata()) != list(titled.getdata())


def test_render_poem_title_still_requires_title_author(tmp_path: Path):
    src = tmp_path / "layout.png"
    _make_png(src, width=640, height=360)
    with pytest.raises(Exception, match="title and author"):
        render_poem_title_still(
            input_path=src, output_path=tmp_path / "o.png", title="", author=""
        )


def test_poem_meta_roundtrip_and_normalize():
    from app.core.projects.models import Shot

    shot = Shot(
        id="sht_1",
        project_id="prj_1",
        scene_id="scn_1",
        title="t",
        script_beat="b",
        duration_s=3.0,
    )
    assert poem_meta.get_poem(shot) == {}
    assert poem_meta.has_poem(shot) is False

    updated = poem_meta.set_poem(
        shot,
        {
            "title": " 相思 ",
            "author": "王维",
            "dynasty": "",
            "lines": ["红豆生南国", {"text": "春来发几枝", "start_s": "1.2"}],
        },
    )
    poem = poem_meta.get_poem(updated)
    assert poem["title"] == "相思"
    assert poem["dynasty"] == "唐"  # default restored
    assert poem["seal"] == "狸"
    assert poem["lines"][0] == {"text": "红豆生南国"}
    assert poem["lines"][1]["start_s"] == pytest.approx(1.2)
    assert poem_meta.has_poem(updated) is True


def test_derive_line_starts_segment_aligned(monkeypatch):
    monkeypatch.setattr(
        timing,
        "transcribe_words",
        lambda *a, **k: {
            "segments": [
                {"text": "红豆生南国", "start": 1.0, "end": 2.4},
                {"text": "春来发几枝", "start": 3.1, "end": 4.5},
            ],
            "words": [],
        },
    )
    starts = timing.derive_line_starts(
        ["红豆生南国", "春来发几枝"], audio_path=Path("/dev/null")
    )
    assert starts == [1.0, 3.1]


def test_derive_line_starts_pause_grouped(monkeypatch):
    # No segments; words with a clear pause between two phrases.
    monkeypatch.setattr(
        timing,
        "transcribe_words",
        lambda *a, **k: {
            "segments": [],
            "words": [
                {"word": "红", "start": 1.0, "end": 1.3},
                {"word": "豆", "start": 1.3, "end": 1.6},
                {"word": "生", "start": 1.6, "end": 1.9},
                {"word": "春", "start": 3.0, "end": 3.3},
                {"word": "来", "start": 3.3, "end": 3.6},
            ],
        },
    )
    starts = timing.derive_line_starts(
        ["红豆生南国", "春来发几枝"], audio_path=Path("/dev/null")
    )
    assert starts == [1.0, 3.0]


def test_derive_line_starts_interpolates_when_short(monkeypatch):
    # Only one onset but three lines -> interpolate the tail monotonically.
    monkeypatch.setattr(
        timing,
        "transcribe_words",
        lambda *a, **k: {
            "segments": [],
            "words": [
                {"word": "红", "start": 1.0, "end": 1.4},
                {"word": "豆", "start": 1.4, "end": 4.0},
            ],
        },
    )
    starts = timing.derive_line_starts(
        ["红豆生南国", "春来发几枝", "愿君多采撷"], audio_path=Path("/dev/null")
    )
    assert len(starts) == 3
    assert starts[0] == 1.0
    assert starts == sorted(starts)
    assert starts[-1] <= 4.0


def test_ref_frame_postprocess_adds_titled_preview(tmp_path: Path):
    pipeline = RefFramePipeline()
    src = tmp_path / "layout.png"
    _make_png(src)
    saved = {"layout": src}
    job = JobRecord(
        id="job_rf",
        pipeline_id="ref_frame",
        asset_kind="layouts",
        status=JobStatus.succeeded,
        name="layout",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={"poem": {"title": "相思", "author": "王维"}},
    )
    pipeline.postprocess_job_outputs(job, saved)
    assert "layout_titled" in saved
    assert Path(saved["layout_titled"]).is_file()
    # The H3-fed layout must remain untouched (text-free).
    assert list(Image.open(src).convert("RGB").getdata()) == list(
        Image.new("RGB", (1728, 960), (210, 225, 235)).getdata()
    )


def test_ref_frame_postprocess_noop_without_poem(tmp_path: Path):
    pipeline = RefFramePipeline()
    src = tmp_path / "layout.png"
    _make_png(src)
    saved = {"layout": src}
    job = JobRecord(
        id="job_rf2",
        pipeline_id="ref_frame",
        asset_kind="layouts",
        status=JobStatus.succeeded,
        name="layout",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={},
    )
    pipeline.postprocess_job_outputs(job, saved)
    assert "layout_titled" not in saved


@pytest.mark.asyncio
async def test_director_set_poem_records_metadata(tmp_projects_dir):
    project = create_project("Poem flow", "A cat recites a poem.")
    shot = Shot(
        id="sht_poem_1",
        project_id=project.id,
        scene_id="sc01",
        title="Title + Line 1",
        script_beat="recites line 1",
        duration_s=3.0,
        status=ShotStatus.ref_frame_pending,
    )
    from app.core.projects.store import save_shot

    save_shot(shot)

    handled = await handle_audio_tool(
        name="set_poem",
        args={
            "shot_id": shot.id,
            "title": "相思",
            "author": "王维",
            "dynasty": "唐",
            "lines": [{"text": "红豆生南国"}],
        },
        project_id=project.id,
        runtime=None,
        actions=[],
        notes=[],
        result_payloads=[],
        images=None,
    )
    assert handled is True
    reloaded = load_shot(project.id, shot.id)
    poem = poem_meta.get_poem(reloaded)
    assert poem["title"] == "相思"
    assert poem["author"] == "王维"
    assert poem["dynasty"] == "唐"
    assert poem["seal"] == "狸"
    assert poem["lines"][0]["text"] == "红豆生南国"


@pytest.mark.asyncio
async def test_director_set_poem_requires_matching_shot(tmp_projects_dir):
    project = create_project("Poem flow 2", "x")
    with pytest.raises(ValueError, match="matches a shot"):
        await handle_audio_tool(
            name="set_poem",
            args={"shot_id": "sht_missing", "title": "a", "author": "b", "lines": [{"text": "x"}]},
            project_id=project.id,
            runtime=None,
            actions=[],
            notes=[],
            result_payloads=None,
            images=None,
        )


def test_set_poem_tool_is_registered():
    from app.agents.director.tool_schema import DIRECTOR_TOOL_SCHEMAS

    names = {t["function"]["name"] for t in DIRECTOR_TOOL_SCHEMAS}
    assert "set_poem" in names
