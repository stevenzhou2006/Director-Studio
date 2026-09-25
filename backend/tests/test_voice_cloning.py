from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from app.config import settings
from app.core.schemas import JobRecord, JobStatus
from app.pipelines.tts import speakers
from app.pipelines.tts.pipeline import TtsPipeline
from app.pipelines.tts import workflow


def _wav_bytes(duration_s: float = 8.0, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * int(duration_s * sample_rate))
    return buffer.getvalue()


@pytest.fixture
def voices_dir(tmp_path, monkeypatch):
    voices = tmp_path / "comfy-voices"
    voices.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "qwen_tts_voices_dir", voices)
    return voices


# ── graph builders ────────────────────────────────────────────────


def test_register_graph_wires_clone_prompt_savevoice_and_saveaudio():
    graph = workflow.build_register_speaker_prompt(
        ref_audio_name="ref.flac",
        ref_text="红豆生南国，春来发几枝。",
        slug="spk_abc",
        job_id="job_1",
    )

    assert graph[workflow.NODE_REF_LOAD]["class_type"] == "LoadAudio"
    assert graph[workflow.NODE_REF_LOAD]["inputs"]["audio"] == "ref.flac"

    clone = graph[workflow.NODE_CLONE_PROMPT]
    assert clone["class_type"] == "FB_Qwen3TTSVoiceClonePrompt"
    assert clone["inputs"]["ref_audio"] == [workflow.NODE_REF_LOAD, 0]
    assert clone["inputs"]["ref_text"] == "红豆生南国，春来发几枝。"
    assert clone["inputs"]["model_choice"] == workflow.SPEAKER_MODEL_CHOICE

    save_voice = graph[workflow.NODE_VOICE_SAVE]
    assert save_voice["class_type"] == "FB_Qwen3TTSSaveVoice"
    assert save_voice["inputs"]["voice_clone_prompt"] == [
        workflow.NODE_CLONE_PROMPT,
        0,
    ]
    assert save_voice["inputs"]["filename"] == "spk_abc"
    assert save_voice["inputs"]["audio"] == [workflow.NODE_REF_LOAD, 0]
    assert save_voice["inputs"]["ref_text"] == "红豆生南国，春来发几枝。"

    # The MCP adapter rejects jobs with no files: the reference passthrough
    # guarantees a mapped SaveAudio output.
    assert graph[workflow.NODE_SAVE]["class_type"] == "SaveAudio"
    assert graph[workflow.NODE_SAVE]["inputs"]["audio"] == [
        workflow.NODE_REF_LOAD,
        0,
    ]


def test_register_graph_requires_ref_text_and_slug():
    with pytest.raises(ValueError, match="ref_text"):
        workflow.build_register_speaker_prompt(
            ref_audio_name="ref.flac", ref_text="  ", slug="spk_abc", job_id="j"
        )
    with pytest.raises(ValueError, match="slug"):
        workflow.build_register_speaker_prompt(
            ref_audio_name="ref.flac", ref_text="x", slug="", job_id="j"
        )


def test_speak_graph_wires_loadspeaker_prompt_and_ref_text():
    graph, seed = workflow.build_speaker_speak_prompt(
        speaker_wav="spk_abc.wav",
        text="床前明月光",
        seed=42,
        job_id="job_2",
    )

    assert seed == 42
    load = graph[workflow.NODE_SPEAKER_LOAD]
    assert load["class_type"] == "FB_Qwen3TTSLoadSpeaker"
    assert load["inputs"]["filename"] == "spk_abc.wav"

    clone = graph[workflow.NODE_SPEAKER_CLONE]
    assert clone["class_type"] == "FB_Qwen3TTSVoiceClone"
    assert clone["inputs"]["target_text"] == "床前明月光"
    assert clone["inputs"]["model_choice"] == workflow.SPEAKER_MODEL_CHOICE
    # Pre-computed features and the stored transcript come from LoadSpeaker.
    assert clone["inputs"]["voice_clone_prompt"] == [
        workflow.NODE_SPEAKER_LOAD,
        0,
    ]
    assert clone["inputs"]["ref_text"] == [workflow.NODE_SPEAKER_LOAD, 2]
    assert clone["inputs"]["unload_model_after_generate"] is True

    assert graph[workflow.NODE_SAVE]["class_type"] == "SaveAudio"
    assert graph[workflow.NODE_SAVE]["inputs"]["audio"] == [
        workflow.NODE_SPEAKER_CLONE,
        0,
    ]


def test_speak_graph_resolves_random_seed_when_none():
    _graph, seed = workflow.build_speaker_speak_prompt(
        speaker_wav="spk_abc.wav", text="hello", seed=None, job_id="job_3"
    )
    assert isinstance(seed, int)


# ── speaker registry ──────────────────────────────────────────────


def test_create_speaker_persists_metadata_and_reference(tmp_projects_dir, voices_dir):
    speaker = speakers.create_speaker(
        project_id="prj_1",
        name="隆昌女孩 · 相思",
        ref_text="红豆生南国，春来发几枝？愿君多采撷，此物最相思。",
        ref_audio_bytes=_wav_bytes(8.0),
        source_filename="xiangsi.wav",
    )

    assert speaker["id"].startswith("spk_")
    assert speaker["slug"] == speaker["id"]
    assert speaker["status"] == speakers.SPEAKER_STATUS_REGISTERING
    assert speaker["engine_ready"] is False
    assert speaker["preview_url"] is not None

    stored = tmp_projects_dir / "prj_1" / "speakers" / f"{speaker['id']}.json"
    assert stored.is_file()
    folder = tmp_projects_dir / "prj_1" / "speakers" / speaker["id"]
    assert (folder / "source.wav").is_file()
    assert (folder / "reference.wav").is_file()


def test_create_speaker_rejects_missing_ref_text(tmp_projects_dir, voices_dir):
    with pytest.raises(ValueError, match="ref_text"):
        speakers.create_speaker(
            project_id="prj_1",
            name="x",
            ref_text="",
            ref_audio_bytes=_wav_bytes(8.0),
            source_filename="a.wav",
        )


def test_create_speaker_rejects_bad_duration(tmp_projects_dir, voices_dir):
    with pytest.raises(ValueError, match="reference audio"):
        speakers.create_speaker(
            project_id="prj_1",
            name="x",
            ref_text="too short",
            ref_audio_bytes=_wav_bytes(0.5),
            source_filename="a.wav",
        )


def test_engine_ready_flips_status_after_files_appear(tmp_projects_dir, voices_dir):
    speaker = speakers.create_speaker(
        project_id="prj_1",
        name="girl",
        ref_text="红豆生南国",
        ref_audio_bytes=_wav_bytes(8.0),
        source_filename="a.wav",
    )
    slug = speaker["slug"]
    (voices_dir / f"{slug}.qvp").write_bytes(b"features")
    (voices_dir / f"{slug}.json").write_text('{"ref_text": "x"}', encoding="utf-8")
    (voices_dir / f"{slug}.wav").write_bytes(b"audio")

    listed = speakers.list_speakers("prj_1")
    assert len(listed) == 1
    assert listed[0]["engine_ready"] is True
    assert listed[0]["status"] == speakers.SPEAKER_STATUS_READY


def test_resolve_speaker_by_id_and_name(tmp_projects_dir, voices_dir):
    speaker = speakers.create_speaker(
        project_id="prj_1",
        name="隆昌女孩",
        ref_text="红豆生南国",
        ref_audio_bytes=_wav_bytes(8.0),
        source_filename="a.wav",
    )
    assert speakers.resolve_speaker("prj_1", speaker["id"])["id"] == speaker["id"]
    assert (
        speakers.resolve_speaker("prj_1", "隆昌女孩")["id"] == speaker["id"]
    )
    assert speakers.resolve_speaker("prj_1", "nope") is None


def test_delete_speaker_removes_registry_and_engine_files(
    tmp_projects_dir, voices_dir
):
    speaker = speakers.create_speaker(
        project_id="prj_1",
        name="girl",
        ref_text="红豆生南国",
        ref_audio_bytes=_wav_bytes(8.0),
        source_filename="a.wav",
    )
    slug = speaker["slug"]
    (voices_dir / f"{slug}.qvp").write_bytes(b"f")
    (voices_dir / f"{slug}.wav").write_bytes(b"a")

    assert speakers.delete_speaker("prj_1", speaker["id"]) is True
    assert speakers.get_speaker("prj_1", speaker["id"]) is None
    assert not (voices_dir / f"{slug}.qvp").exists()
    assert not (voices_dir / f"{slug}.wav").exists()
    assert speakers.delete_speaker("prj_1", speaker["id"]) is False


# ── pipeline branching ────────────────────────────────────────────


def test_pipeline_register_style_uses_uploaded_reference():
    pipeline = TtsPipeline()
    job = JobRecord(
        id="job_reg",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.queued,
        name="Speaker · girl",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={
            "style": "register-speaker",
            "slug": "spk_abc",
            "ref_text": "红豆生南国",
        },
    )
    prompt, _seed = pipeline.build_prompt(
        job, uploaded_images={"reference": "uploaded_ref.flac"}
    )
    assert prompt[workflow.NODE_CLONE_PROMPT]["class_type"] == (
        "FB_Qwen3TTSVoiceClonePrompt"
    )
    assert prompt[workflow.NODE_REF_LOAD]["inputs"]["audio"] == (
        "uploaded_ref.flac"
    )


def test_pipeline_register_style_requires_upload():
    pipeline = TtsPipeline()
    job = JobRecord(
        id="job_reg2",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.queued,
        name="Speaker",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={"style": "register-speaker", "slug": "spk_abc", "ref_text": "x"},
    )
    with pytest.raises(ValueError, match="uploaded reference"):
        pipeline.build_prompt(job, uploaded_images={})


def test_pipeline_saved_speaker_style_uses_speaker_wav():
    pipeline = TtsPipeline()
    job = JobRecord(
        id="job_speak",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.queued,
        name="Speech",
        seed=9,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={
            "style": "saved-speaker",
            "text": "床前明月光",
            "speaker_wav": "spk_abc.wav",
        },
    )
    prompt, seed = pipeline.build_prompt(job, uploaded_images={})
    assert seed == 9
    assert prompt[workflow.NODE_SPEAKER_CLONE]["inputs"]["target_text"] == (
        "床前明月光"
    )


def test_pipeline_saved_speaker_requires_speaker_wav():
    pipeline = TtsPipeline()
    job = JobRecord(
        id="job_speak2",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.queued,
        name="Speech",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={"style": "saved-speaker", "text": "hi"},
    )
    with pytest.raises(ValueError, match="speaker_wav"):
        pipeline.build_prompt(job, uploaded_images={})


def test_on_job_succeeded_marks_speaker_ready(tmp_projects_dir, voices_dir):
    speaker = speakers.create_speaker(
        project_id="prj_1",
        name="girl",
        ref_text="红豆生南国",
        ref_audio_bytes=_wav_bytes(8.0),
        source_filename="a.wav",
    )
    slug = speaker["slug"]
    (voices_dir / f"{slug}.qvp").write_bytes(b"f")
    (voices_dir / f"{slug}.wav").write_bytes(b"a")

    job = JobRecord(
        id="job_reg_ok",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.succeeded,
        name="Speaker · girl",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        project_id="prj_1",
        params={
            "style": "register-speaker",
            "speaker_id": speaker["id"],
            "slug": slug,
            "ref_text": "红豆生南国",
            "project_id": "prj_1",
        },
    )
    TtsPipeline().on_job_succeeded(job)
    assert speakers.get_speaker("prj_1", speaker["id"])["status"] == (
        speakers.SPEAKER_STATUS_READY
    )


def test_on_job_succeeded_flags_missing_engine_files(tmp_projects_dir, voices_dir):
    speaker = speakers.create_speaker(
        project_id="prj_1",
        name="girl",
        ref_text="红豆生南国",
        ref_audio_bytes=_wav_bytes(8.0),
        source_filename="a.wav",
    )
    job = JobRecord(
        id="job_reg_missing",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.succeeded,
        name="Speaker · girl",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        project_id="prj_1",
        params={
            "style": "register-speaker",
            "speaker_id": speaker["id"],
            "slug": speaker["slug"],
            "project_id": "prj_1",
        },
    )
    TtsPipeline().on_job_succeeded(job)
    assert speakers.get_speaker("prj_1", speaker["id"])["status"] == (
        speakers.SPEAKER_STATUS_FAILED
    )
