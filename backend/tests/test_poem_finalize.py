"""Post-H3 poem finalize: font-layer overlay + original-audio swap (C3/C4)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.jobs import poem_finalize, store
from app.core.jobs.shot_sync import on_pipeline_job_terminal
from app.core.projects.models import Shot, ShotStatus, ShotVoiceRef
from app.core.projects.store import create_project, load_shot, save_shot
from app.core.schemas import JobRecord, JobStatus, OutputSlot
from app.pipelines.poem_overlay import timing

_FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg required")


def _make_tone_video(path: Path, *, seconds: int, freq: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x203040:s=576x1024:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={seconds}",
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


def _make_tone_wav(path: Path, *, seconds: int, freq: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={seconds}",
            str(path),
        ],
        check=True,
    )


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    lib = tmp_path / "library"
    projects = tmp_path / "projects"
    jobs.mkdir()
    lib.mkdir()
    projects.mkdir()
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "library_root", lib)
    monkeypatch.setattr(settings, "projects_dir", projects)
    return tmp_path


def _poem_shot(project_id: str, **meta_updates) -> Shot:
    meta = {
        "poem": {
            "title": "相思",
            "author": "王维",
            "dynasty": "唐",
            "seal": "狸",
            "lines": [{"text": "红豆生南国"}],
        }
    }
    meta.update(meta_updates)
    shot = Shot(
        id="sht_finalize01",
        project_id=project_id,
        scene_id="sc01",
        title="Title + Line 1",
        script_beat="recites line 1",
        duration_s=3.6,
        status=ShotStatus.queued,
        meta=meta,
    )
    save_shot(shot)
    return shot


def _h3_job(tmp_path, project_id: str, shot_id: str, *, job_id="job_h3_fin01") -> JobRecord:
    jdir = tmp_path / "jobs" / job_id
    (jdir / "outputs").mkdir(parents=True)
    video = jdir / "outputs" / "video.mp4"
    _make_tone_video(video, seconds=6, freq=440)
    job = JobRecord(
        id=job_id,
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        status=JobStatus.succeeded,
        name="h3:Title + Line 1",
        params={"shot_id": shot_id, "project_id": project_id},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        outputs={
            "video": OutputSlot(
                key="video",
                label="H3 Ref2AV Video",
                path=str(video),
                filename="video.mp4",
            )
        },
    )
    store.save_job(job)
    return job


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

def test_skip_reason_no_poem(isolated_data):
    project = create_project("Fin no poem", "script")
    shot = _poem_shot(project.id)
    shot = shot.model_copy(update={"meta": {}})
    save_shot(shot)
    job = _h3_job(isolated_data, project.id, shot.id)
    reason = poem_finalize.poem_finalize_skip_reason(shot, job)
    assert reason is not None and "poem" in reason


def test_skip_reason_opt_out(isolated_data):
    project = create_project("Fin opt out", "script")
    shot = _poem_shot(project.id, poem_auto_overlay=False)
    job = _h3_job(isolated_data, project.id, shot.id)
    reason = poem_finalize.poem_finalize_skip_reason(shot, job)
    assert reason is not None and "disabled" in reason


def test_skip_reason_already_finalized(isolated_data):
    project = create_project("Fin twice", "script")
    shot = _poem_shot(project.id)
    job = _h3_job(isolated_data, project.id, shot.id)
    store.save_job(job.model_copy(update={"params": {**job.params, "poem_finalized": "job_x"}}))
    reloaded = store.load_job(job.id)
    reason = poem_finalize.poem_finalize_skip_reason(shot, reloaded)
    assert reason is not None and "already finalized" in reason


def test_skip_reason_existing_overlay(isolated_data):
    project = create_project("Fin existing overlay", "script")
    shot = _poem_shot(project.id)
    job = _h3_job(isolated_data, project.id, shot.id)
    existing = store.create_job(
        pipeline_id="poem_overlay",
        asset_kind="productions",
        name="finalize: existing",
        params={"source_h3_job_id": job.id, "title": "t", "author": "a", "lines": []},
        project_id=project.id,
    )
    reason = poem_finalize.poem_finalize_skip_reason(shot, job)
    assert reason is not None and existing.id in reason


def test_eligible_when_poem_and_video_present(isolated_data):
    project = create_project("Fin eligible", "script")
    shot = _poem_shot(project.id)
    job = _h3_job(isolated_data, project.id, shot.id)
    assert poem_finalize.poem_finalize_skip_reason(shot, job) is None


# ---------------------------------------------------------------------------
# run_poem_finalize
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finalize_with_recitation_replaces_audio(isolated_data, monkeypatch):
    project = create_project("Fin with audio", "script")
    shot = _poem_shot(project.id)
    job = _h3_job(isolated_data, project.id, shot.id)

    recitation = isolated_data / "rec.flac"
    _make_tone_wav(recitation, seconds=2, freq=880)

    monkeypatch.setattr(
        timing, "resolve_recitation_audio", lambda _shot: (recitation, 0.5)
    )
    monkeypatch.setattr(timing, "derive_line_starts", lambda lines, **kw: [0.5])

    started: list[tuple[JobRecord, dict]] = []

    async def fake_start(j, *, images=None):
        started.append((j, images or {}))
        return j

    monkeypatch.setattr(
        "app.core.jobs.runner.start_pipeline_job", AsyncMock(side_effect=fake_start)
    )

    await poem_finalize.run_poem_finalize(job, shot)

    assert len(started) == 1
    overlay_job, images = started[0]
    assert overlay_job.pipeline_id == "poem_overlay"
    params = overlay_job.params
    assert params["replace_audio"] is True
    assert params["source_h3_job_id"] == job.id
    assert params["title"] == "相思"
    assert params["author"] == "王维"
    assert params["dynasty"] == "唐"
    assert params["lines"] == [{"text": "红豆生南国", "start_s": 0.5}]
    assert "video" in images and "audio" in images
    assert images["audio"][1] == recitation.read_bytes()


@pytest.mark.asyncio
async def test_finalize_without_recitation_keeps_h3_audio(isolated_data, monkeypatch):
    project = create_project("Fin no audio", "script")
    shot = _poem_shot(project.id)
    job = _h3_job(isolated_data, project.id, shot.id)

    def raise_no_audio(_shot):
        raise timing.PoemTimingError("shot has no voice references to time against")

    monkeypatch.setattr(timing, "resolve_recitation_audio", raise_no_audio)

    started: list[tuple[JobRecord, dict]] = []

    async def fake_start(j, *, images=None):
        started.append((j, images or {}))
        return j

    monkeypatch.setattr(
        "app.core.jobs.runner.start_pipeline_job", AsyncMock(side_effect=fake_start)
    )

    await poem_finalize.run_poem_finalize(job, shot)

    assert len(started) == 1
    overlay_job, images = started[0]
    # H3's natively generated audio must be preserved.
    assert overlay_job.params["replace_audio"] is False
    assert "audio" not in images
    # No recitation to sync against → deterministic even spread.
    assert overlay_job.params["lines"][0]["start_s"] == 0.0


@pytest.mark.asyncio
async def test_finalize_skips_when_asr_fails_with_audio_attached(
    isolated_data, monkeypatch
):
    project = create_project("Fin asr fail", "script")
    shot = _poem_shot(project.id)
    job = _h3_job(isolated_data, project.id, shot.id)

    recitation = isolated_data / "rec.flac"
    _make_tone_wav(recitation, seconds=2, freq=880)
    monkeypatch.setattr(
        timing, "resolve_recitation_audio", lambda _shot: (recitation, 0.5)
    )

    def fail_timing(lines, **kw):
        raise timing.PoemTimingError("ASR produced no speech")

    monkeypatch.setattr(timing, "derive_line_starts", fail_timing)

    start_mock = AsyncMock()
    monkeypatch.setattr("app.core.jobs.runner.start_pipeline_job", start_mock)

    await poem_finalize.run_poem_finalize(job, shot)
    start_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_respects_explicit_start_s(isolated_data, monkeypatch):
    project = create_project("Fin explicit", "script")
    shot = _poem_shot(project.id)
    shot = shot.model_copy(
        update={
            "meta": {
                **shot.meta,
                "poem": {
                    **shot.meta["poem"],
                    "lines": [{"text": "红豆生南国", "start_s": 1.25}],
                },
            }
        }
    )
    save_shot(shot)
    job = _h3_job(isolated_data, project.id, shot.id)

    def raise_no_audio(_shot):
        raise timing.PoemTimingError("none")

    monkeypatch.setattr(timing, "resolve_recitation_audio", raise_no_audio)
    started: list[JobRecord] = []

    async def fake_start(j, *, images=None):
        started.append(j)
        return j

    monkeypatch.setattr(
        "app.core.jobs.runner.start_pipeline_job", AsyncMock(side_effect=fake_start)
    )

    await poem_finalize.run_poem_finalize(job, shot)
    assert started[0].params["lines"][0]["start_s"] == 1.25


# ---------------------------------------------------------------------------
# C4 write-back
# ---------------------------------------------------------------------------

def test_write_back_swaps_slots(isolated_data):
    project = create_project("Writeback", "script")
    shot = _poem_shot(project.id)
    h3 = _h3_job(isolated_data, project.id, shot.id)

    overlay_dir = isolated_data / "jobs" / "job_overlay_wb" / "outputs"
    overlay_dir.mkdir(parents=True)
    overlay_file = overlay_dir / "final.mp4"
    _make_tone_video(overlay_file, seconds=6, freq=880)

    overlay_job = JobRecord(
        id="job_overlay_wb",
        pipeline_id="poem_overlay",
        asset_kind="productions",
        status=JobStatus.succeeded,
        name="finalize: Title + Line 1",
        params={
            "source_h3_job_id": h3.id,
            "shot_id": shot.id,
            "project_id": project.id,
            "replace_audio": True,
        },
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        outputs={
            "video": OutputSlot(
                key="video",
                label="Video with poem subtitles",
                path=str(overlay_file),
                filename="final.mp4",
            )
        },
    )
    store.save_job(overlay_job)

    on_pipeline_job_terminal(overlay_job)

    updated = store.load_job(h3.id)
    assert updated is not None
    assert updated.params["poem_finalized"] == overlay_job.id
    assert updated.outputs["video"].filename == "video.mp4"
    assert updated.outputs["video_raw"].filename == "video_raw.mp4"
    # The canonical video is now the finalized overlay content.
    final_bytes = (
        isolated_data / "jobs" / h3.id / "outputs" / "video.mp4"
    ).read_bytes()
    assert final_bytes == overlay_file.read_bytes()
    # The untouched H3 render survives as the raw slot.
    raw_bytes = (
        isolated_data / "jobs" / h3.id / "outputs" / "video_raw.mp4"
    ).read_bytes()
    assert raw_bytes != final_bytes


def test_write_back_idempotent(isolated_data):
    project = create_project("Writeback idem", "script")
    shot = _poem_shot(project.id)
    h3 = _h3_job(isolated_data, project.id, shot.id)

    overlay_dir = isolated_data / "jobs" / "job_overlay_idem" / "outputs"
    overlay_dir.mkdir(parents=True)
    overlay_file = overlay_dir / "final.mp4"
    _make_tone_video(overlay_file, seconds=6, freq=880)

    overlay_job = JobRecord(
        id="job_overlay_idem",
        pipeline_id="poem_overlay",
        asset_kind="productions",
        status=JobStatus.succeeded,
        name="finalize",
        params={"source_h3_job_id": h3.id, "project_id": project.id},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        outputs={
            "video": OutputSlot(
                key="video",
                label="v",
                path=str(overlay_file),
                filename="final.mp4",
            )
        },
    )
    store.save_job(overlay_job)

    on_pipeline_job_terminal(overlay_job)
    first = store.load_job(h3.id)
    on_pipeline_job_terminal(store.load_job(overlay_job.id) or overlay_job)
    second = store.load_job(h3.id)

    assert first.params["poem_finalized"] == overlay_job.id
    assert second.params["poem_finalized"] == overlay_job.id
    assert second.outputs["video"].filename == "video.mp4"


def test_write_back_ignores_manual_overlay(isolated_data):
    """A Director-invoked overlay without a source H3 binding never writes back."""
    project = create_project("Manual overlay", "script")
    overlay_job = JobRecord(
        id="job_overlay_manual",
        pipeline_id="poem_overlay",
        asset_kind="productions",
        status=JobStatus.succeeded,
        name="poem overlay: manual",
        params={"title": "t", "author": "a", "project_id": project.id},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    store.save_job(overlay_job)
    on_pipeline_job_terminal(overlay_job)
    assert store.load_job(overlay_job.id).params.get("poem_finalized") is None


# ---------------------------------------------------------------------------
# ffmpeg-level audio replacement
# ---------------------------------------------------------------------------

@needs_ffmpeg
def test_render_poem_overlay_replaces_audio_track(tmp_path: Path):
    from app.pipelines.poem_overlay import overlay

    source = tmp_path / "src.mp4"
    _make_tone_video(source, seconds=6, freq=440)
    replacement = tmp_path / "rec.wav"
    _make_tone_wav(replacement, seconds=2, freq=880)
    output = tmp_path / "out.mp4"

    meta = overlay.render_poem_overlay(
        input_path=source,
        output_path=output,
        title="相思",
        author="王维",
        dynasty="唐",
        lines=[("红豆生南国", 0.5)],
        replacement_audio=replacement,
    )
    assert meta["audio_replaced"] is True

    # Output audio spans the full video (padded), and after the 2s recording
    # ends it is silence — proving the source 440Hz track was replaced.
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "csv=p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert float(probe.strip()) >= 5.5

    silence = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(output),
            "-af",
            "silencedetect=n=-50dB:d=1.5",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stderr
    import re as _re

    match = _re.search(r"silence_start:\s*([0-9.]+)", silence)
    assert match is not None
    silence_start = float(match.group(1))
    assert 1.5 <= silence_start <= 3.5


@needs_ffmpeg
def test_render_terminates_on_system_ffmpeg_6x(tmp_path: Path, monkeypatch):
    """Regression: ffmpeg 6.x never lets -shortest finish a -loop 1 + apad graph.

    The service runs the system ffmpeg, so force /usr/bin/ffmpeg explicitly and
    assert the encode terminates (the -t cap) instead of spinning forever.
    """
    import os

    system_ffmpeg = Path("/usr/bin/ffmpeg")
    if not system_ffmpeg.is_file():
        pytest.skip("system ffmpeg not present")
    monkeypatch.setenv("PATH", f"/usr/bin:{os.environ.get('PATH', '')}")

    from app.pipelines.poem_overlay import overlay

    source = tmp_path / "src.mp4"
    _make_tone_video(source, seconds=4, freq=440)
    replacement = tmp_path / "rec.wav"
    _make_tone_wav(replacement, seconds=2, freq=880)
    output = tmp_path / "out.mp4"

    meta = overlay.render_poem_overlay(
        input_path=source,
        output_path=output,
        title="相思",
        author="王维",
        dynasty="唐",
        lines=[("红豆生南国", 0.5)],
        replacement_audio=replacement,
    )
    assert meta["audio_replaced"] is True
    assert output.is_file() and output.stat().st_size > 0
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert 3.5 <= float(probe.strip()) <= 4.5


@needs_ffmpeg
def test_render_poem_overlay_without_replacement_keeps_source_audio(tmp_path: Path):
    from app.pipelines.poem_overlay import overlay

    source = tmp_path / "src.mp4"
    _make_tone_video(source, seconds=4, freq=440)
    output = tmp_path / "out.mp4"

    meta = overlay.render_poem_overlay(
        input_path=source,
        output_path=output,
        title="相思",
        author="王维",
        dynasty="唐",
        lines=[("红豆生南国", 0.5)],
    )
    assert meta["audio_replaced"] is False
    # No silent stretch: the full-length source audio was copied through.
    silence = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(output),
            "-af",
            "silencedetect=n=-50dB:d=1.5",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stderr
    assert "silence_start" not in silence
