"""Tests for concatenating finished Shot clips with ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.agents.director.chat import _run_tools
from app.config import settings
from app.core.jobs.store import create_job, job_dir, save_job
from app.core.projects.models import Shot, ShotStatus
from app.core.projects.store import create_project, save_project, save_shot
from app.core.schemas import JobStatus, OutputSlot


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    jobs = tmp_path / "jobs"
    library = tmp_path / "library"
    for path in (projects, jobs, library):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "projects_dir", projects)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "library_root", library)
    return {"projects": projects, "jobs": jobs, "root": tmp_path}


def _ffmpeg_bin() -> str:
    resolved = shutil.which("ffmpeg")
    if not resolved:
        pytest.skip("ffmpeg is required for concat tests")
    return resolved


def _write_clip(
    path: Path,
    *,
    color: str,
    duration: float = 0.5,
    with_audio: bool = False,
) -> None:
    ffmpeg = _ffmpeg_bin()
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=64x64:d={duration}:r=8",
    ]
    if with_audio:
        command.extend(["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"])
    command.extend(["-pix_fmt", "yuv420p"])
    if with_audio:
        command.extend(["-c:a", "aac", "-shortest"])
    else:
        command.append("-an")
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True, text=True)


def _make_shot(project_id: str, shot_id: str, title: str) -> Shot:
    return Shot(
        id=shot_id,
        project_id=project_id,
        scene_id="sc01",
        title=title,
        script_beat=title,
        duration_s=1.0,
        status=ShotStatus.succeeded,
    )


def _succeed_clip(project_id: str, shot_id: str, clip: Path) -> None:
    job = create_job(
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        name=f"{shot_id} clip",
        project_id=project_id,
        params={"shot_id": shot_id, "project_id": project_id},
    )
    out_dir = job_dir(job.id, project_id=project_id) / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "video.mp4"
    shutil.copy2(clip, dest)
    job.status = JobStatus.succeeded
    job.outputs = {
        "video": OutputSlot(
            key="video",
            label="video",
            path=str(dest),
            filename="video.mp4",
            url=f"/api/files/jobs/{job.id}/outputs/video.mp4",
        )
    }
    save_job(job)


def _project_with_shots(shot_ids: list[str]) -> str:
    project = create_project("Flycat", "INT. HALL")
    shots = [_make_shot(project.id, sid, f"Shot {sid}") for sid in shot_ids]
    for shot in shots:
        save_shot(shot)
    save_project(project.model_copy(update={"shot_ids": shot_ids}))
    return project.id


def test_resolve_latest_succeeded_clip_ignores_newer_failed(isolated):
    from app.core.media.clip_generations import resolve_latest_succeeded_clip

    project_id = _project_with_shots(["sht_a"])
    clip = isolated["root"] / "a.mp4"
    _write_clip(clip, color="red")
    _succeed_clip(project_id, "sht_a", clip)

    newer = create_job(
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        name="failed retry",
        project_id=project_id,
        params={"shot_id": "sht_a", "project_id": project_id},
    )
    newer.status = JobStatus.failed
    save_job(newer)

    resolved = resolve_latest_succeeded_clip(
        project_id=project_id, source_shot_id="sht_a"
    )
    assert resolved.source_shot_id == "sht_a"
    assert resolved.path.name == "video.mp4"
    assert resolved.path.is_file()


def test_concatenate_project_shots_stream_copy(isolated):
    from app.core.media.concat import concatenate_project_shots

    project_id = _project_with_shots(["sht_1", "sht_2"])
    for index, color in enumerate(["red", "blue"], start=1):
        clip = isolated["root"] / f"{color}.mp4"
        _write_clip(clip, color=color)
        _succeed_clip(project_id, f"sht_{index}", clip)

    result = concatenate_project_shots(project_id=project_id)

    assert result["ok"] is True
    assert result["clip_count"] == 2
    assert result["method"] == "copy"
    out = Path(result["output_path"])
    assert out.is_file()
    assert out.parent == isolated["projects"] / project_id / "renders"
    assert result["url"].startswith(
        f"/api/files/projects/{project_id}/renders/{out.name}?v="
    )
    assert result["duration_s"] >= 0.9
    assert [clip["shot_id"] for clip in result["clips"]] == ["sht_1", "sht_2"]


def test_concatenate_project_shots_reencode_with_audio(isolated):
    from app.core.media.concat import concatenate_project_shots

    project_id = _project_with_shots(["sht_1", "sht_2"])
    for index, color in enumerate(["green", "yellow"], start=1):
        clip = isolated["root"] / f"{color}_audio.mp4"
        _write_clip(clip, color=color, with_audio=True)
        _succeed_clip(project_id, f"sht_{index}", clip)

    result = concatenate_project_shots(
        project_id=project_id,
        output_name="flycat_final",
        reencode=True,
    )

    assert result["method"] == "reencode"
    out = Path(result["output_path"])
    assert out.name == "flycat_final.mp4"
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        pytest.skip("ffprobe is required for concat tests")
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip()


def test_concatenate_reports_shots_missing_a_clip(isolated):
    from app.core.media.clip_generations import ClipGenerationError
    from app.core.media.concat import concatenate_project_shots

    project_id = _project_with_shots(["sht_ok", "sht_missing"])
    clip = isolated["root"] / "ok.mp4"
    _write_clip(clip, color="red")
    _succeed_clip(project_id, "sht_ok", clip)

    with pytest.raises(ClipGenerationError) as excinfo:
        concatenate_project_shots(project_id=project_id)
    assert "sht_missing" in str(excinfo.value)


@pytest.mark.asyncio
async def test_concatenate_tool_note_reports_host_path(isolated, monkeypatch):
    project_id = _project_with_shots(["sht_1", "sht_2"])
    for index, color in enumerate(["red", "blue"], start=1):
        clip = isolated["root"] / f"tool_{color}.mp4"
        _write_clip(clip, color=color)
        _succeed_clip(project_id, f"sht_{index}", clip)

    actions: list[str] = []
    payloads: list[dict] = []
    notes, _touched = await _run_tools(
        project_id=project_id,
        tools=[
            {
                "name": "concatenate_shots",
                "args": {"output_name": "final_cut"},
            }
        ],
        svc=object(),
        actions=actions,
        result_payloads=payloads,
    )

    assert actions == ["concatenate_shots"]
    assert payloads[0]["ok"] is True
    output_path = payloads[0]["output_path"]
    assert output_path.endswith("final_cut.mp4")
    joined = "\n".join(notes)
    assert output_path in joined
    assert "final_cut.mp4" in joined
    assert "2 shot clip" in joined


@pytest.mark.asyncio
async def test_concatenate_tool_failure_is_reported_not_raised(isolated):
    project_id = _project_with_shots(["sht_only"])
    actions: list[str] = []
    payloads: list[dict] = []
    notes, _touched = await _run_tools(
        project_id=project_id,
        tools=[{"name": "concatenate_shots", "args": {}}],
        svc=object(),
        actions=actions,
        result_payloads=payloads,
    )

    assert actions == []
    assert payloads[0]["ok"] is False
    assert "failed" in notes[0].lower()


def test_concat_tool_is_offered_to_the_model():
    from app.agents.director.tool_schema import DIRECTOR_TOOL_SCHEMAS

    names = {tool["function"]["name"] for tool in DIRECTOR_TOOL_SCHEMAS}
    assert "concatenate_shots" in names
    tool = next(
        tool
        for tool in DIRECTOR_TOOL_SCHEMAS
        if tool["function"]["name"] == "concatenate_shots"
    )
    props = tool["function"]["parameters"]["properties"]
    assert set(props) == {"output_name", "output_kind", "reencode"}
    assert tool["function"]["parameters"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_concatenate_endpoint_returns_path_and_url(isolated):
    from app.api.projects import (
        ConcatenateResponse,
        ConcatenateShotsBody,
        concatenate_project_endpoint,
    )

    project_id = _project_with_shots(["sht_1", "sht_2"])
    for index, color in enumerate(["red", "blue"], start=1):
        clip = isolated["root"] / f"api_{color}.mp4"
        _write_clip(clip, color=color)
        _succeed_clip(project_id, f"sht_{index}", clip)

    response = await concatenate_project_endpoint(
        project_id,
        ConcatenateShotsBody(output_name="api_final"),
    )

    assert isinstance(response, ConcatenateResponse)
    assert response.clip_count == 2
    assert response.url.startswith(
        f"/api/files/projects/{project_id}/renders/api_final.mp4?v="
    )
    assert Path(response.output_path).is_file()


@pytest.mark.asyncio
async def test_concatenate_endpoint_maps_missing_project_and_missing_clip(isolated):
    from fastapi import HTTPException

    from app.api.projects import concatenate_project_endpoint

    with pytest.raises(HTTPException) as missing_project:
        await concatenate_project_endpoint("prj_nope", None)
    assert missing_project.value.status_code == 404

    project_id = _project_with_shots(["sht_only"])
    with pytest.raises(HTTPException) as missing_clip:
        await concatenate_project_endpoint(project_id, None)
    assert missing_clip.value.status_code == 409
