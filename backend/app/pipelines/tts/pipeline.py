"""Qwen3-TTS speech pipeline (ComfyUI-backed, audio output)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from ...core.library.audio import probe_audio
from ...core.schemas import ComfyImageRef, JobRecord, LibraryAsset
from ..base import Pipeline
from . import workflow

_H3_REF_MIN_S = 2.0
_H3_REF_MAX_S = 15.0

# ffmpeg atempo supports 0.5–2.0 per filter; keep the UI within that range.
SPEED_MIN = 0.5
SPEED_MAX = 2.0
SPEED_STEP = 0.1


def _non_negative_float(value: Any) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return result if result > 0 else 0.0


def _speed_or_default(value: Any) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return 1.0
    if speed < SPEED_MIN or speed > SPEED_MAX:
        return 1.0
    return speed


class TtsPipeline(Pipeline):
    id = "tts"
    asset_kind = "voices"
    display_name = "Speech (Qwen3-TTS)"
    description = (
        "Qwen3-TTS speech/recitation through ComfyUI. Supports the verified 四川隆昌 "
        "小女孩 dialect recipe, the native Sichuan CustomVoice speaker (Eric), and "
        "custom voice-design instructions."
    )
    generation_kind = "audio"
    enabled = True

    @property
    def output_labels(self) -> dict[str, str]:
        return {
            "audio": "Speech audio",
            "audio_padded": "Padded speech (H3 reference)",
        }

    def build_prompt(
        self,
        job: JobRecord,
        *,
        uploaded_images: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        params = job.params or {}
        style = str(params.get("style") or "longchang-girl").strip()
        if style not in workflow.STYLES:
            raise ValueError(
                f"unsupported style {style!r}; expected one of {', '.join(workflow.STYLES)}"
            )
        if style == "register-speaker":
            return self._build_register(job, uploaded_images)
        if style == "saved-speaker":
            return self._build_saved_speaker(job)
        text = str(params.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        instruct, pairs, warnings = workflow.build_instruct(
            style=style,
            text=text,
            respell=params.get("respell"),
            age=str(params.get("age") or workflow.DEFAULT_AGE),
            rhyme=str(params.get("rhyme") or workflow.DEFAULT_RHYME),
            emotion=str(params.get("emotion") or workflow.DEFAULT_EMOTION),
            instruct=params.get("instruct"),
        )
        params["instruct"] = instruct
        params["used_respell"] = ",".join(f"{a}={b}" for a, b in pairs)
        params["respell_pairs"] = [f"{a}={b}" for a, b in pairs]
        if warnings:
            params["warnings"] = warnings
        prompt, seed = workflow.build_tts_prompt(
            text=text,
            instruct=instruct,
            style=style,
            seed=job.seed,
            job_id=job.id,
            speaker=str(params.get("speaker") or workflow.DEFAULT_ERIC_SPEAKER),
            model_choice=str(params.get("model_choice") or "1.7B"),
            top_p=float(params.get("top_p") or 0.8),
            top_k=int(params.get("top_k") or 20),
            temperature=float(params.get("temperature") or 1.0),
            repetition_penalty=float(params.get("repetition_penalty") or 1.05),
        )
        return prompt, seed

    def _build_register(
        self, job: JobRecord, uploaded_images: dict[str, str]
    ) -> tuple[dict[str, Any], int]:
        params = job.params or {}
        ref_audio_name = str(uploaded_images.get("reference") or "").strip()
        if not ref_audio_name:
            raise ValueError("register-speaker requires an uploaded reference audio")
        slug = str(params.get("slug") or "").strip()
        if not slug:
            raise ValueError("register-speaker requires a slug")
        prompt = workflow.build_register_speaker_prompt(
            ref_audio_name=ref_audio_name,
            ref_text=str(params.get("ref_text") or ""),
            slug=slug,
            job_id=job.id,
        )
        return prompt, int(job.seed or 0)

    def _build_saved_speaker(self, job: JobRecord) -> tuple[dict[str, Any], int]:
        params = job.params or {}
        speaker_wav = str(params.get("speaker_wav") or "").strip()
        if not speaker_wav:
            raise ValueError("saved-speaker requires speaker_wav")
        text = str(params.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        return workflow.build_speaker_speak_prompt(
            speaker_wav=speaker_wav,
            text=text,
            seed=job.seed,
            job_id=job.id,
            language=str(params.get("language") or "Chinese"),
            top_p=float(params.get("top_p") or 0.8),
            top_k=int(params.get("top_k") or 20),
            temperature=float(params.get("temperature") or 1.0),
            repetition_penalty=float(params.get("repetition_penalty") or 1.05),
        )

    def on_job_succeeded(self, job: JobRecord) -> None:
        """Mark the speaker ready once its engine files have been written."""
        params = job.params or {}
        if str(params.get("style") or "") != "register-speaker":
            return
        spk_id = str(params.get("speaker_id") or "").strip()
        project_id = str(params.get("project_id") or job.project_id or "").strip()
        if not spk_id or not project_id:
            return
        from . import speakers

        try:
            if speakers.speaker_is_ready(spk_id):
                speakers.set_status(project_id, spk_id, speakers.SPEAKER_STATUS_READY)
            else:
                speakers.set_status(
                    project_id,
                    spk_id,
                    speakers.SPEAKER_STATUS_FAILED,
                    error="registration finished but engine voice files are missing",
                )
        except ValueError:
            pass

    def map_history_outputs(
        self,
        history: dict[str, Any],
        *,
        job: JobRecord | None = None,
    ) -> dict[str, ComfyImageRef]:
        return workflow.map_history_outputs(history, job=job)

    def postprocess_job_outputs(
        self, job: JobRecord, saved: dict[str, Any]
    ) -> None:
        """Apply speed + lead/tail silence for H3 mouth-sync handoff.

        Qwen3-TTS has no native rate control, so the tempo change is done with
        ffmpeg ``atempo``. The padded track is keyed ``audio_padded`` so
        ``enrich_job_urls`` and ``save_asset_from_job`` (which glob by key)
        keep it.
        """
        params = job.params or {}
        lead = _non_negative_float(params.get("lead_silence_s"))
        tail = _non_negative_float(params.get("tail_silence_s"))
        speed = _speed_or_default(params.get("speed"))
        if lead <= 0 and tail <= 0 and abs(speed - 1.0) < 1e-3:
            return
        source = saved.get("audio")
        if not source:
            return
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            params["warnings"] = list(params.get("warnings") or []) + [
                "ffmpeg unavailable; speed/silence were not applied"
            ]
            return
        source_path = Path(source)
        destination = source_path.with_name(f"{source_path.stem}_padded.flac")
        filters: list[str] = []
        if abs(speed - 1.0) >= 1e-3:
            filters.append(f"atempo={speed:.3f}")
        if lead > 0:
            filters.append(f"adelay={round(lead * 1000)}:all=1")
        if tail > 0:
            filters.append(f"apad=pad_dur={tail:.3f}")
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-i",
                str(source_path),
                "-af",
                ",".join(filters),
                "-c:a",
                "flac",
                str(destination),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and destination.is_file():
            saved["audio_padded"] = destination
        else:
            params["warnings"] = list(params.get("warnings") or []) + [
                "ffmpeg failed; speed/silence were not applied"
            ]

    def library_meta(self, job: JobRecord) -> dict[str, Any]:
        return dict(job.params or {})

    def save_to_library(
        self,
        job: JobRecord,
        *,
        name: str | None = None,
        notes: str | None = None,
        project_id: str | None = None,
    ) -> LibraryAsset:
        from ...core.library import save_asset_from_job

        params = job.params or {}
        resolved = project_id or job.project_id
        file_keys = [
            key for key in ("audio", "audio_padded") if key in job.outputs
        ] or ["audio"]
        # The H3 mouth-sync reference is the padded take when present, else raw.
        h3_file_key = "audio_padded" if "audio_padded" in job.outputs else "audio"
        h3_slot = job.outputs.get(h3_file_key)
        duration_s: float | None = None
        if h3_slot and h3_slot.path:
            try:
                duration_s = probe_audio(Path(h3_slot.path)).duration_s
            except (OSError, ValueError):
                duration_s = None
        h3_ready = bool(
            duration_s is not None
            and _H3_REF_MIN_S <= duration_s <= _H3_REF_MAX_S
        )
        return save_asset_from_job(
            job,
            name=name,
            notes=notes,
            file_keys=file_keys,
            input_keys=[],
            meta={
                "style": params.get("style"),
                "text": params.get("text"),
                "used_respell": params.get("used_respell"),
                "instruct": params.get("instruct"),
                "lead_silence_s": params.get("lead_silence_s"),
                "warnings": params.get("warnings") or [],
                "duration_s": duration_s,
                "h3_ready": h3_ready,
                "h3_file_key": h3_file_key,
                "speaker_id": params.get("speaker_id"),
                "speaker_name": params.get("speaker_name"),
            },
            project_id=resolved,
        )
