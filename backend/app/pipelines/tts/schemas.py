from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...core.schemas import JobRecord, JobStatus, LibraryAsset, OutputSlot


class TtsJobResponse(BaseModel):
    id: str
    status: JobStatus
    name: str
    notes: str = ""
    seed: int | None = None
    fixed_seed: bool = False
    error: str | None = None
    comfy_prompt_id: str | None = None
    created_at: str
    updated_at: str
    outputs: dict[str, OutputSlot] = Field(default_factory=dict)
    output_order: list[str] = Field(default_factory=list)
    input_previews: dict[str, str] = Field(default_factory=dict)
    pipeline_id: str = "tts"
    style: str | None = None
    speaker_id: str | None = None

    @classmethod
    def from_job(cls, job: JobRecord, labels: dict[str, str] | None = None) -> TtsJobResponse:
        outs = dict(job.outputs or {})
        if labels:
            for k, slot in outs.items():
                if slot and labels.get(k):
                    outs[k] = slot.model_copy(update={"label": labels[k]})
        order = [k for k in ("audio", "audio_padded") if k in outs] + [
            k for k in outs if k not in ("audio", "audio_padded")
        ]
        params = job.params or {}
        return cls(
            id=job.id,
            status=job.status,
            name=job.name,
            notes=job.notes,
            seed=job.seed,
            fixed_seed=job.fixed_seed,
            error=job.error,
            comfy_prompt_id=job.comfy_prompt_id,
            created_at=job.created_at,
            updated_at=job.updated_at,
            outputs=outs,
            output_order=order,
            input_previews=job.input_previews,
            pipeline_id=job.pipeline_id,
            style=str(params.get("style") or "") or None,
            speaker_id=str(params.get("speaker_id") or "") or None,
        )


class SpeakerRecord(BaseModel):
    id: str
    project_id: str
    name: str
    slug: str
    ref_text: str
    source: str = ""
    source_asset_id: str | None = None
    duration_s: float | None = None
    status: str
    register_job_id: str | None = None
    created_at: str
    engine_ready: bool = False
    engine_files: dict[str, bool] = Field(default_factory=dict)
    preview_url: str | None = None


class SpeakerListResponse(BaseModel):
    items: list[SpeakerRecord]


class RegisterSpeakerResponse(BaseModel):
    speaker: SpeakerRecord
    job: TtsJobResponse


class SaveTtsRequest(BaseModel):
    name: str | None = None
    notes: str | None = None
    project_id: str | None = None


class VoiceRecord(BaseModel):
    id: str
    name: str
    notes: str = ""
    seed: int | None = None
    job_id: str
    created_at: str
    files: dict[str, str | None] = Field(default_factory=dict)
    urls: dict[str, str] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None

    @classmethod
    def from_library(cls, asset: LibraryAsset) -> VoiceRecord:
        return cls(
            id=asset.id,
            name=asset.name,
            notes=asset.notes,
            seed=asset.seed,
            job_id=asset.job_id,
            created_at=asset.created_at,
            files=dict(asset.files or {}),
            urls=dict(asset.urls or {}),
            meta=dict(asset.meta or {}),
            project_id=asset.project_id,
        )
