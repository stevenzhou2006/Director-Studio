"""Voice Cloning Studio endpoints: saved speakers + speech generation."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ...config import settings
from ...core.jobs import (
    cancel_job,
    create_job,
    enrich_job_urls,
    load_job,
    start_pipeline_job,
)
from ...core.schemas import JobStatus
from ...pipelines.registry import get_pipeline
from . import pipeline as pipeline_mod
from . import speakers
from .schemas import (
    RegisterSpeakerResponse,
    SaveTtsRequest,
    SpeakerListResponse,
    SpeakerRecord,
    TtsJobResponse,
    VoiceRecord,
)

router = APIRouter(tags=["tts"])

_ALLOWED_REF_EXT = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}


def _job_response(job) -> TtsJobResponse:
    pipe = get_pipeline("tts")
    job = enrich_job_urls(job, labels=pipe.output_labels)
    return TtsJobResponse.from_job(job, labels=pipe.output_labels)


def _require_project(project_id: str) -> str:
    project_id = (project_id or "").strip()
    if not project_id:
        raise HTTPException(400, "project_id is required")
    return project_id


def _speaker_record(project_id: str, speaker: dict) -> SpeakerRecord:
    return SpeakerRecord.model_validate(speaker)


async def _read_reference(upload: UploadFile | None) -> tuple[str, bytes]:
    if upload is None:
        raise HTTPException(400, "reference audio file is required")
    filename = upload.filename or "reference.wav"
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_REF_EXT:
        raise HTTPException(
            400,
            f"unsupported reference audio type {ext!r}; "
            f"allowed: {', '.join(sorted(_ALLOWED_REF_EXT))}",
        )
    data = await upload.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(400, f"reference audio exceeds {settings.max_upload_mb}MB")
    if not data:
        raise HTTPException(400, "reference audio file is empty")
    return filename, data


@router.get("/tts/speakers", response_model=SpeakerListResponse)
async def list_speakers(project_id: str) -> SpeakerListResponse:
    pid = _require_project(project_id)
    return SpeakerListResponse(
        items=[_speaker_record(pid, s) for s in speakers.list_speakers(pid)]
    )


@router.get("/tts/speakers/{spk_id}", response_model=SpeakerRecord)
async def get_speaker(spk_id: str, project_id: str) -> SpeakerRecord:
    pid = _require_project(project_id)
    speaker = speakers.get_speaker(pid, spk_id)
    if speaker is None:
        raise HTTPException(404, "Speaker not found")
    return _speaker_record(pid, speaker)


@router.post("/tts/speakers", response_model=RegisterSpeakerResponse)
async def register_speaker(
    project_id: str = Form(...),
    name: str = Form(...),
    ref_text: str = Form(...),
    reference_audio: UploadFile = File(...),
    source_asset_id: str = Form(""),
) -> RegisterSpeakerResponse:
    pid = _require_project(project_id)
    filename, data = await _read_reference(reference_audio)
    try:
        speaker = speakers.create_speaker(
            project_id=pid,
            name=name,
            ref_text=ref_text,
            ref_audio_bytes=data,
            source_filename=filename,
            source_asset_id=(source_asset_id or "").strip() or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    pipe = get_pipeline("tts")
    job = create_job(
        pipeline_id=pipe.id,
        asset_kind=pipe.asset_kind,
        name=f"Speaker · {speaker['name']}",
        notes=f"Register saved speaker from {filename}",
        params={
            "style": "register-speaker",
            "speaker_id": speaker["id"],
            "slug": speaker["slug"],
            "ref_text": speaker["ref_text"],
            "project_id": pid,
        },
        project_id=pid,
    )
    job = await start_pipeline_job(job, images={"reference": (filename, data)})
    speaker = speakers.attach_register_job(pid, speaker["id"], job.id)
    return RegisterSpeakerResponse(
        speaker=_speaker_record(pid, speaker),
        job=_job_response(job),
    )


@router.delete("/tts/speakers/{spk_id}")
async def delete_speaker(spk_id: str, project_id: str) -> dict:
    pid = _require_project(project_id)
    if not speakers.delete_speaker(pid, spk_id):
        raise HTTPException(404, "Speaker not found")
    return {"ok": True, "id": spk_id}


@router.post("/tts/generate", response_model=TtsJobResponse)
async def generate_speech(
    project_id: str = Form(...),
    speaker_id: str = Form(...),
    text: str = Form(...),
    lead_silence_s: str = Form("0"),
    tail_silence_s: str = Form("0"),
    speed: str = Form("1"),
    seed: str = Form(""),
    fixed_seed: bool = Form(False),
) -> TtsJobResponse:
    pid = _require_project(project_id)
    text = (text or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    speaker = speakers.get_speaker(pid, speaker_id.strip())
    if speaker is None:
        raise HTTPException(404, "Speaker not found")
    if not speakers.speaker_is_ready(speaker["id"]):
        raise HTTPException(
            409,
            "Speaker is not ready yet (voice features missing). "
            "Re-register the reference audio first.",
        )
    try:
        lead = float(lead_silence_s or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "lead_silence_s must be a number") from None
    if lead < 0 or lead > 10:
        raise HTTPException(400, "lead_silence_s must be between 0 and 10")
    try:
        tail = float(tail_silence_s or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "tail_silence_s must be a number") from None
    if tail < 0 or tail > 10:
        raise HTTPException(400, "tail_silence_s must be between 0 and 10")
    try:
        speed_val = float(speed or 1)
    except (TypeError, ValueError):
        raise HTTPException(400, "speed must be a number") from None
    if speed_val < pipeline_mod.SPEED_MIN or speed_val > pipeline_mod.SPEED_MAX:
        raise HTTPException(
            400,
            f"speed must be between {pipeline_mod.SPEED_MIN} and "
            f"{pipeline_mod.SPEED_MAX}",
        )
    seed_val: int | None = None
    if seed.strip():
        try:
            seed_val = int(seed.strip())
        except ValueError:
            raise HTTPException(400, "seed must be an integer") from None

    pipe = get_pipeline("tts")
    job = create_job(
        pipeline_id=pipe.id,
        asset_kind=pipe.asset_kind,
        name=f"Speech · {text[:16]}",
        notes=" ".join(text.split())[:400],
        params={
            "style": "saved-speaker",
            "text": text,
            "speaker_id": speaker["id"],
            "speaker_name": speaker.get("name"),
            "speaker_wav": speakers.speaker_wav_name(speaker["id"]),
            "lead_silence_s": lead,
            "tail_silence_s": tail,
            "speed": speed_val,
            "project_id": pid,
        },
        seed=seed_val,
        fixed_seed=fixed_seed,
        project_id=pid,
    )
    job = await start_pipeline_job(job, images={})
    return _job_response(job)


@router.get("/tts/jobs/{job_id}", response_model=TtsJobResponse)
async def get_tts_job(job_id: str) -> TtsJobResponse:
    job = load_job(job_id)
    if not job or job.pipeline_id != "tts":
        raise HTTPException(404, "Job not found")
    return _job_response(job)


@router.post("/tts/jobs/{job_id}/cancel", response_model=TtsJobResponse)
async def cancel_tts_job(job_id: str) -> TtsJobResponse:
    job = load_job(job_id)
    if not job or job.pipeline_id != "tts":
        raise HTTPException(404, "Job not found")
    job = await cancel_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_response(job)


@router.post("/tts/jobs/{job_id}/save", response_model=VoiceRecord)
async def save_tts_job(job_id: str, body: SaveTtsRequest | None = None) -> VoiceRecord:
    job = load_job(job_id)
    if not job or job.pipeline_id != "tts":
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.succeeded:
        raise HTTPException(400, f"Job status is {job.status}, need succeeded")
    style = str((job.params or {}).get("style") or "")
    if style == "register-speaker":
        raise HTTPException(
            400,
            "Registration jobs have no speech to save; the speaker itself is "
            "already stored once the job succeeds.",
        )
    pipe = get_pipeline("tts")
    proj = (body.project_id if body else None) or job.project_id
    if isinstance(proj, str):
        proj = proj.strip() or None
    try:
        asset = pipe.save_to_library(
            job,
            name=body.name if body else None,
            notes=body.notes if body else None,
            project_id=proj,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return VoiceRecord.from_library(asset)
