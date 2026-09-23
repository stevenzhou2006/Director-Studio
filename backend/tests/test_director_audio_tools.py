from __future__ import annotations

from typing import Any

import pytest

from app.agents.director.tool_handlers.audio import handle_audio_tool
from app.agents.director.tool_schema import (
    DIRECTOR_TOOL_SCHEMAS,
    POEM_OVERLAY_TOOL,
    SPEECH_TOOL,
    director_chat_guides,
)
from app.core.projects.store import create_project
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
    assert overlay["properties"]["lines"]["items"]["required"] == ["text", "start_s"]
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
