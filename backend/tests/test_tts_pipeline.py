from __future__ import annotations

import io
import shutil
import wave
from pathlib import Path

import pytest

from app.core.schemas import JobRecord, JobStatus, LibraryAsset, OutputSlot
from app.pipelines.tts import workflow
from app.pipelines.tts.pipeline import TtsPipeline


def _wav_bytes(duration_s: float = 0.5, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * int(duration_s * sample_rate))
    return buffer.getvalue()


def test_longchang_girl_requires_and_embeds_respell_clause():
    instruct, pairs, warnings = workflow.build_instruct(
        style="longchang-girl",
        text="空山不见人",
        respell="长=藏,深=森,知=资",
    )

    assert pairs == [("长", "藏"), ("深", "森"), ("知", "资")]
    assert warnings == []
    assert "'长'读成接近'藏'" in instruct
    assert "隆昌" in instruct
    assert "标点符号都不要读出来" in instruct


def test_auto_respell_picks_only_characters_present_in_the_text():
    pairs = workflow.auto_respell("空山不见人，返景入深林，复照青苔上")

    assert ("深", "森") in pairs
    assert ("照", "早") in pairs
    assert ("山", "三") in pairs
    assert ("春", "村") not in pairs


def test_missing_respell_warns_about_accent_drift():
    _instruct, pairs, warnings = workflow.build_instruct(
        style="longchang-girl",
        text="ABCDEFG",
        respell="",
    )

    assert pairs == []
    assert warnings and "普通话" in warnings[0]


def test_eric_style_uses_custom_voice_node_with_native_speaker():
    prompt, _seed = workflow.build_tts_prompt(
        text="你好",
        instruct="深情吟诵",
        style="eric",
        seed=7,
        job_id="job_test",
        speaker="Eric",
    )

    node = prompt[workflow.NODE_TTS]
    assert node["class_type"] == "FB_Qwen3TTSCustomVoice"
    assert node["inputs"]["speaker"] == "Eric"
    assert prompt[workflow.NODE_SAVE]["class_type"] == "SaveAudio"
    assert prompt[workflow.NODE_SAVE]["inputs"]["audio"] == [workflow.NODE_TTS, 0]


def test_voice_design_style_maps_audio_history_output():
    prompt, seed = workflow.build_tts_prompt(
        text="你好",
        instruct="instruct",
        style="longchang-girl",
        seed=None,
        job_id="job_test",
    )

    assert prompt[workflow.NODE_TTS]["class_type"] == "FB_Qwen3TTSVoiceDesign"
    assert isinstance(seed, int)

    history = {
        "outputs": {
            workflow.NODE_SAVE: {
                "audio": [
                    {"filename": "x.flac", "subfolder": "audio", "type": "output"}
                ]
            }
        }
    }
    mapped = workflow.map_history_outputs(history)
    assert mapped["audio"].filename == "x.flac"
    assert mapped["audio"].subfolder == "audio"


def test_pipeline_declares_audio_generation_and_voice_asset():
    pipeline = TtsPipeline()
    assert pipeline.generation_kind == "audio"
    assert pipeline.asset_kind == "voices"
    assert "audio" in pipeline.output_labels


def test_build_prompt_records_used_respell_and_instruct():
    pipeline = TtsPipeline()
    job = JobRecord(
        id="job_tts_build",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.queued,
        name="recite",
        seed=11,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={"text": "空山不见人", "style": "longchang-girl", "respell": "长=藏"},
    )

    prompt, seed = pipeline.build_prompt(job, uploaded_images={})

    assert prompt[workflow.NODE_TTS]["class_type"] == "FB_Qwen3TTSVoiceDesign"
    assert seed == 11
    assert job.params["used_respell"] == "长=藏"
    assert "instruct" in job.params


def test_build_prompt_rejects_unknown_style():
    pipeline = TtsPipeline()
    job = JobRecord(
        id="job_tts_bad",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.queued,
        name="recite",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={"text": "hi", "style": "bogus"},
    )

    with pytest.raises(ValueError, match="unsupported style"):
        pipeline.build_prompt(job, uploaded_images={})


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_postprocess_pads_lead_silence_for_h3(tmp_path: Path):
    pipeline = TtsPipeline()
    audio = tmp_path / "audio.wav"
    audio.write_bytes(_wav_bytes())
    job = JobRecord(
        id="job_tts_pad",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.succeeded,
        name="recite",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={"lead_silence_s": 1.0},
    )
    saved: dict[str, object] = {"audio": audio}

    pipeline.postprocess_job_outputs(job, saved)

    padded = saved.get("audio_padded")
    assert padded is not None
    assert Path(padded).is_file()


def _save_job(duration_s: float) -> JobRecord:
    return JobRecord(
        id="job_tts_save",
        pipeline_id="tts",
        asset_kind="voices",
        status=JobStatus.succeeded,
        name="recite",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        params={"style": "longchang-girl", "text": "红豆生南国"},
        outputs={
            "audio": OutputSlot(
                key="audio", label="a", path="/tmp/audio.flac"
            )
        },
    )


def _stub_save(monkeypatch, duration_s: float) -> dict:
    captured: dict = {}

    def fake_save_asset_from_job(job, **kwargs):
        captured.update(kwargs)
        return LibraryAsset(
            id="voi_x",
            kind="voices",
            name=kwargs.get("name") or "v",
            pipeline_id="tts",
            job_id=job.id,
            created_at="2026-01-01T00:00:00+00:00",
            files={"audio": "audio.flac"},
            meta=kwargs.get("meta") or {},
        )

    class _Meta:
        pass

    meta = _Meta()
    meta.duration_s = duration_s

    monkeypatch.setattr(
        "app.core.library.save_asset_from_job", fake_save_asset_from_job
    )
    monkeypatch.setattr(
        "app.pipelines.tts.pipeline.probe_audio", lambda path: meta
    )
    return captured


def test_save_to_library_marks_h3_ready_within_window(monkeypatch):
    captured = _stub_save(monkeypatch, 3.5)
    asset = TtsPipeline().save_to_library(
        _save_job(3.5), name="Line 1", project_id="prj_1"
    )
    assert asset.meta["h3_ready"] is True
    assert asset.meta["duration_s"] == 3.5
    assert asset.meta["h3_file_key"] == "audio"
    assert captured["meta"]["h3_ready"] is True


def test_save_to_library_not_h3_ready_outside_window(monkeypatch):
    _stub_save(monkeypatch, 20.0)
    asset = TtsPipeline().save_to_library(
        _save_job(20.0), name="Too long", project_id="prj_1"
    )
    assert asset.meta["h3_ready"] is False
    assert asset.meta["duration_s"] == 20.0
