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
        del uploaded_images
        params = job.params or {}
        text = str(params.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        style = str(params.get("style") or "longchang-girl").strip()
        if style not in workflow.STYLES:
            raise ValueError(
                f"unsupported style {style!r}; expected one of {', '.join(workflow.STYLES)}"
            )
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
        """Pad the recitation with lead silence for H3 mouth-sync handoff."""
        params = job.params or {}
        try:
            lead = float(params.get("lead_silence_s") or 0.0)
        except (TypeError, ValueError):
            lead = 0.0
        if lead <= 0:
            return
        source = saved.get("audio")
        if not source:
            return
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            params["warnings"] = list(params.get("warnings") or []) + [
                "ffmpeg unavailable; lead silence was not added"
            ]
            return
        source_path = Path(source)
        destination = source_path.with_name(f"{source_path.stem}_pad.flac")
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-i",
                str(source_path),
                "-af",
                f"adelay={round(lead * 1000)}",
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
            },
            project_id=resolved,
        )
