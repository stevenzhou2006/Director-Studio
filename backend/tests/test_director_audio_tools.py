from __future__ import annotations

from typing import Any

import pytest

from app.agents.director.tool_handlers.audio import (
    _bind_voice_to_shot,
    handle_audio_tool,
)
from app.agents.director.tool_schema import (
    DIRECTOR_TOOL_SCHEMAS,
    POEM_OVERLAY_TOOL,
    SPEECH_TOOL,
    director_chat_guides,
)
from app.core.projects.models import Shot, ShotStatus, ShotVoiceRef
from app.core.projects.store import create_project, load_shot, save_shot
from app.core.library.store import write_asset
from app.core.schemas import JobRecord, JobStatus, LibraryAsset, OutputSlot

_NOW = "2026-01-01T00:00:00+00:00"


def _tool(name: str) -> dict[str, Any]:
    return next(
        item for item in DIRECTOR_TOOL_SCHEMAS if item["function"]["name"] == name
    )


def test_speech_and_overlay_tools_are_exposed_with_expected_contracts():
    speech = _tool("generate_tts_audio")["function"]["parameters"]
    assert speech["required"] == ["text"]
    assert speech["properties"]["style"]["enum"] == [
        "longchang-girl",
        "eric",
        "custom",
    ]
    assert speech["properties"]["style"]["default"] == "longchang-girl"

    overlay = _tool("overlay_poem_subtitles")["function"]["parameters"]
    assert overlay["required"] == ["title", "author", "lines"]
    # start_s is optional: it is auto-derived from ASR on the bound recitation.
    assert overlay["properties"]["lines"]["items"]["required"] == ["text"]
    assert SPEECH_TOOL["function"]["name"] == "generate_tts_audio"
    assert POEM_OVERLAY_TOOL["function"]["name"] == "overlay_poem_subtitles"


def test_chat_guides_load_audio_and_overlay_guidance_on_intent(tmp_projects_dir):
    project = create_project("Guides", "A short film.")

    audio = director_chat_guides(
        project, include_visual_qc=False, current_message="用隆昌口音朗读这首诗"
    )
    overlay = director_chat_guides(
        project, include_visual_qc=False, current_message="加竖排书法字幕"
    )
    plain = director_chat_guides(
        project, include_visual_qc=False, current_message="review shot 1"
    )

    assert "audio-generation" in audio
    assert "poem-subtitle-overlay" in overlay
    assert "audio-generation" not in plain
    assert "poem-subtitle-overlay" not in plain


class _TtsPipeline:
    def __init__(self) -> None:
        self.saved = None

    def save_to_library(self, job, **kwargs):
        self.saved = (job, kwargs)
        return LibraryAsset(
            id="voi_tts_1",
            kind="voices",
            name=kwargs["name"],
            pipeline_id="tts",
            job_id=job.id,
            created_at=_NOW,
            files={"audio": "audio.flac"},
            urls={"audio": "/api/files/library/voices/voi_tts_1/audio.flac"},
        )


class _Runtime:
    def __init__(self, *, terminal: JobRecord, pipeline: Any = None) -> None:
        self.terminal = terminal
        self.pipeline = pipeline
        self.created: dict[str, Any] = {}

    def create_job(self, **kwargs):
        self.created = kwargs
        return JobRecord(
            id=self.terminal.id,
            pipeline_id=kwargs["pipeline_id"],
            asset_kind=kwargs["asset_kind"],
            status=JobStatus.queued,
            name=kwargs["name"],
            params=kwargs["params"],
            seed=kwargs.get("seed"),
            created_at=_NOW,
            updated_at=_NOW,
            project_id=kwargs.get("project_id"),
        )

    async def start_pipeline_job(self, job, *, images=None):
        return job

    async def await_pipeline_job(self, job_id):
        return self.terminal

    def get_pipeline(self, pipeline_id):
        return self.pipeline

    def load_job(self, job_id):
        if job_id == self.terminal.id:
            return self.terminal
        return getattr(self, "other_job", None)


@pytest.mark.asyncio
async def test_generate_tts_audio_creates_job_and_saves_voice_asset(tmp_projects_dir):
    project = create_project("TTS", "A short film.")
    terminal = JobRecord(
        id="job_tts_1",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.succeeded,
        name="Speech",
        created_at=_NOW,
        updated_at=_NOW,
        project_id=project.id,
        params={"used_respell": "长=藏", "warnings": []},
        outputs={
            "audio": OutputSlot(
                key="audio",
                label="Speech audio",
                url="/api/files/jobs/job_tts_1/outputs/audio.flac",
            )
        },
    )
    pipeline = _TtsPipeline()
    runtime = _Runtime(terminal=terminal, pipeline=pipeline)
    actions: list[str] = []
    notes: list[str] = []
    payloads: list[dict] = []

    handled = await handle_audio_tool(
        name="generate_tts_audio",
        args={
            "text": "空山不见人",
            "style": "longchang-girl",
            "respell": "长=藏,深=森,知=资",
            "lead_silence_s": 1.0,
        },
        project_id=project.id,
        runtime=runtime,
        actions=actions,
        notes=notes,
        result_payloads=payloads,
        images=[],
    )

    assert handled is True
    assert runtime.created["pipeline_id"] == "tts"
    assert runtime.created["params"]["lead_silence_s"] == 1.0
    assert actions == ["generate_tts_audio:voi_tts_1"]
    assert payloads[0]["ok"] is True
    assert payloads[0]["audio_url"].endswith("audio.flac")
    assert pipeline.saved is not None
    assert payloads[0]["h3_reference_ready"] is False


@pytest.mark.asyncio
async def test_generate_tts_audio_requires_text(tmp_projects_dir):
    project = create_project("TTS", "A short film.")
    runtime = _Runtime(terminal=JobRecord(
        id="job_x", pipeline_id="tts", asset_kind="voices",
        status=JobStatus.succeeded, name="x", created_at=_NOW, updated_at=_NOW,
    ))
    with pytest.raises(ValueError, match="requires text"):
        await handle_audio_tool(
            name="generate_tts_audio",
            args={},
            project_id=project.id,
            runtime=runtime,
            actions=[],
            notes=[],
            result_payloads=None,
            images=None,
        )


def _ready_voice_asset(**overrides: Any) -> LibraryAsset:
    base: dict[str, Any] = {
        "id": "voi_ready_1",
        "kind": "voices",
        "name": "Longchang line 1",
        "pipeline_id": "tts",
        "job_id": "job_tts_1",
        "created_at": _NOW,
        "files": {"audio": "audio.flac"},
        "urls": {"audio": "/api/files/library/voices/voi_ready_1/audio.flac"},
        "meta": {"h3_ready": True, "duration_s": 3.0, "h3_file_key": "audio"},
    }
    base.update(overrides)
    return LibraryAsset(**base)


def _plain_shot(project_id: str, shot_id: str) -> Shot:
    shot = Shot(
        id=shot_id,
        project_id=project_id,
        scene_id="sc01",
        title="Line 1",
        script_beat="recites line 1",
        duration_s=3.0,
        status=ShotStatus.ref_frame_pending,
    )
    save_shot(shot)
    return shot


def test_bind_voice_to_shot_attaches_h3_ready_voice(tmp_projects_dir):
    project = create_project("Bind", "A film.")
    shot = _plain_shot(project.id, "sht_bind_1")

    note = _bind_voice_to_shot(
        asset=_ready_voice_asset(),
        args={"shot_id": shot.id},
        project_id=project.id,
        speaker="",
    )

    assert note is not None and "Bound" in note
    reloaded = load_shot(project.id, shot.id)
    assert len(reloaded.voice_refs) == 1
    ref = reloaded.voice_refs[0]
    assert ref.asset_id == "voi_ready_1"
    assert ref.audio_index == 1
    assert ref.file_key == "audio"
    assert (reloaded.meta or {}).get("prompt_voice_signature") == ""


def test_bind_voice_skips_when_not_h3_ready(tmp_projects_dir):
    project = create_project("Bind2", "A film.")
    shot = _plain_shot(project.id, "sht_bind_2")

    note = _bind_voice_to_shot(
        asset=_ready_voice_asset(
            meta={"h3_ready": False, "duration_s": 20.0, "h3_file_key": "audio"}
        ),
        args={"shot_id": shot.id},
        project_id=project.id,
        speaker="",
    )

    assert "NOT bound" in note
    assert load_shot(project.id, shot.id).voice_refs == []


def test_bind_voice_is_idempotent_for_same_asset(tmp_projects_dir):
    project = create_project("Bind3", "A film.")
    shot = _plain_shot(project.id, "sht_bind_3")
    _bind_voice_to_shot(
        asset=_ready_voice_asset(),
        args={"shot_id": shot.id},
        project_id=project.id,
        speaker="",
    )
    note = _bind_voice_to_shot(
        asset=_ready_voice_asset(),
        args={"shot_id": shot.id},
        project_id=project.id,
        speaker="",
    )
    assert "already bound" in note
    assert len(load_shot(project.id, shot.id).voice_refs) == 1


def test_bind_voice_noop_without_shot_selector(tmp_projects_dir):
    project = create_project("Bind4", "A film.")
    note = _bind_voice_to_shot(
        asset=_ready_voice_asset(),
        args={},
        project_id=project.id,
        speaker="",
    )
    assert note is None


def _persist_voice(project_id: str, asset_id: str, *, h3_ready: bool) -> LibraryAsset:
    return write_asset(
        LibraryAsset(
            id=asset_id,
            kind="voices",
            name=f"Voice {asset_id}",
            pipeline_id="tts",
            job_id="job_seed",
            created_at=_NOW,
            files={"audio": "audio.flac"},
            urls={},
            meta={"h3_ready": h3_ready, "duration_s": 3.0, "h3_file_key": "audio"},
            project_id=project_id,
        )
    )


def _shot_with_voice(project_id: str, shot_id: str, voice_asset_id: str) -> Shot:
    shot = Shot(
        id=shot_id,
        project_id=project_id,
        scene_id="sc01",
        title="Line 1",
        script_beat="recites line 1",
        duration_s=3.0,
        status=ShotStatus.ref_frame_pending,
        voice_refs=[
            ShotVoiceRef(asset_id=voice_asset_id, audio_index=1, file_key="audio")
        ],
    )
    save_shot(shot)
    return shot


def _succeeded_terminal(project_id: str) -> JobRecord:
    return JobRecord(
        id="job_tts_guard",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.succeeded,
        name="recite",
        created_at=_NOW,
        updated_at=_NOW,
        project_id=project_id,
        params={"used_respell": "长=藏", "warnings": []},
        outputs={
            "audio": OutputSlot(
                key="audio",
                label="Speech audio",
                url="/api/files/jobs/job_tts_guard/outputs/audio.flac",
            )
        },
    )


async def _run_tts(project_id: str, args: dict[str, Any]) -> _Runtime:
    runtime = _Runtime(
        terminal=_succeeded_terminal(project_id), pipeline=_TtsPipeline()
    )
    await handle_audio_tool(
        name="generate_tts_audio",
        args=args,
        project_id=project_id,
        runtime=runtime,
        actions=[],
        notes=[],
        result_payloads=[],
        images=[],
    )
    return runtime


@pytest.mark.asyncio
async def test_generate_tts_audio_skips_when_shot_has_h3_ready_voice(tmp_projects_dir):
    project = create_project("Guard", "A film.")
    _persist_voice(project.id, "voi_ready_9", h3_ready=True)
    shot = _shot_with_voice(project.id, "sht_guard_1", "voi_ready_9")

    runtime = _Runtime(
        terminal=_succeeded_terminal(project.id), pipeline=_TtsPipeline()
    )
    actions: list[str] = []
    notes: list[str] = []
    payloads: list[dict] = []
    handled = await handle_audio_tool(
        name="generate_tts_audio",
        args={"text": "红豆生南国", "shot_id": shot.id},
        project_id=project.id,
        runtime=runtime,
        actions=actions,
        notes=notes,
        result_payloads=payloads,
        images=[],
    )

    assert handled is True
    assert runtime.created == {}  # no TTS job was created
    assert any("Skipped" in n for n in notes)
    assert payloads[0]["skipped"] is True
    assert payloads[0]["shot_id"] == shot.id


@pytest.mark.asyncio
async def test_generate_tts_audio_generates_when_shot_has_no_voice(tmp_projects_dir):
    project = create_project("Guard2", "A film.")
    shot = _plain_shot(project.id, "sht_guard_2")

    runtime = await _run_tts(project.id, {"text": "红豆生南国", "shot_id": shot.id})
    assert runtime.created.get("pipeline_id") == "tts"


@pytest.mark.asyncio
async def test_generate_tts_audio_generates_when_attached_voice_not_ready(
    tmp_projects_dir,
):
    project = create_project("Guard3", "A film.")
    _persist_voice(project.id, "voi_notready", h3_ready=False)
    shot = _shot_with_voice(project.id, "sht_guard_3", "voi_notready")

    runtime = await _run_tts(project.id, {"text": "红豆生南国", "shot_id": shot.id})
    assert runtime.created.get("pipeline_id") == "tts"


@pytest.mark.asyncio
async def test_generate_tts_audio_force_overrides_guard(tmp_projects_dir):
    project = create_project("Guard4", "A film.")
    _persist_voice(project.id, "voi_ready_10", h3_ready=True)
    shot = _shot_with_voice(project.id, "sht_guard_4", "voi_ready_10")

    runtime = await _run_tts(
        project.id, {"text": "红豆生南国", "shot_id": shot.id, "force": True}
    )
    assert runtime.created.get("pipeline_id") == "tts"


@pytest.mark.asyncio
async def test_overlay_poem_subtitles_uses_source_job_video(tmp_projects_dir, tmp_path):
    project = create_project("Overlay", "A short film.")
    source_video = tmp_path / "clip.mp4"
    source_video.write_bytes(b"fake-video-bytes")

    source_job = JobRecord(
        id="job_source",
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        status=JobStatus.succeeded,
        name="shot",
        created_at=_NOW,
        updated_at=_NOW,
        project_id=project.id,
        outputs={
            "video": OutputSlot(
                key="video",
                label="Video",
                path=str(source_video),
                url="/api/files/jobs/job_source/outputs/video.mp4",
            )
        },
    )
    terminal = JobRecord(
        id="job_ov_1",
        pipeline_id="poem_overlay",
        asset_kind="productions",
        status=JobStatus.succeeded,
        name="poem overlay: 鹿柴",
        created_at=_NOW,
        updated_at=_NOW,
        project_id=project.id,
        outputs={
            "video": OutputSlot(
                key="video",
                label="Video with poem subtitles",
                path=str(tmp_path / "out.mp4"),
                url="/api/files/jobs/job_ov_1/outputs/video.mp4",
            )
        },
    )
    runtime = _Runtime(terminal=terminal)
    runtime.other_job = source_job
    actions: list[str] = []
    notes: list[str] = []
    payloads: list[dict] = []

    handled = await handle_audio_tool(
        name="overlay_poem_subtitles",
        args={
            "source_job_id": "job_source",
            "title": "鹿柴",
            "author": "王维",
            "lines": [
                {"text": "空山不见人", "start_s": 1.06},
                {"text": "但闻人语响", "start_s": 3.26},
            ],
        },
        project_id=project.id,
        runtime=runtime,
        actions=actions,
        notes=notes,
        result_payloads=payloads,
        images=None,
    )

    assert handled is True
    assert runtime.created["pipeline_id"] == "poem_overlay"
    assert runtime.created["params"]["lines"][0]["start_s"] == 1.06
    assert actions == ["overlay_poem_subtitles:job_ov_1"]
    assert payloads[0]["video_url"].endswith("video.mp4")
    assert "鹿柴" in notes[0]


@pytest.mark.asyncio
async def test_overlay_poem_subtitles_requires_a_source(tmp_projects_dir):
    project = create_project("Overlay", "A short film.")
    runtime = _Runtime(terminal=JobRecord(
        id="job_x", pipeline_id="poem_overlay", asset_kind="productions",
        status=JobStatus.succeeded, name="x", created_at=_NOW, updated_at=_NOW,
    ))
    with pytest.raises(ValueError, match="requires source_shot_id or source_job_id"):
        await handle_audio_tool(
            name="overlay_poem_subtitles",
            args={"title": "鹿柴", "author": "王维", "lines": [{"text": "x", "start_s": 0}]},
            project_id=project.id,
            runtime=runtime,
            actions=[],
            notes=[],
            result_payloads=None,
            images=None,
        )
