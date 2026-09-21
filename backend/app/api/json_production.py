"""JSON Production Mode storyboard import/load API."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from ..config import settings
from ..core.h3.frames import frames_for_seconds
from ..core.h3.prompt import compose_h3_prompt, validate_h3_prompt
from ..core.jobs import create_job, start_pipeline_job
from ..core.library.images import resolve_asset_image
from ..core.library.store import asset_dir, load_asset
from ..core.prompting import effective_global_prompt, ensure_global_prompt_in_h3
from ..core.projects import (
    JsonProductionAudio,
    JsonProductionDocument,
    JsonProductionPicture,
    JsonProductionShot,
    JsonProductionStoredAsset,
    Project,
    delete_json_production_asset,
    list_json_production_assets,
    load_json_production_asset,
    load_json_production_document,
    load_project,
    save_json_production_asset,
    save_json_production_document,
)
from ..core.projects.models import ProjectMode
from ..pipelines.h3_ref2va.schemas import H3Ref2VaJobResponse

router = APIRouter(tags=["json-production"])

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a"}


def _require_json_project(project_id: str) -> Project:
    project = load_project(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if project.mode != ProjectMode.json_production:
        raise HTTPException(
            409,
            "production storyboard is only available for json_production projects",
        )
    return project


@router.get(
    "/projects/{project_id}/production-storyboard",
    response_model=JsonProductionDocument,
)
async def get_production_storyboard(project_id: str) -> JsonProductionDocument:
    _require_json_project(project_id)
    return load_json_production_document(project_id)


@router.put(
    "/projects/{project_id}/production-storyboard",
    response_model=JsonProductionDocument,
)
async def put_production_storyboard(
    project_id: str,
    body: JsonProductionDocument,
) -> JsonProductionDocument:
    _require_json_project(project_id)
    current = load_json_production_document(project_id)
    document = body.model_copy(update={"revision": current.revision + 1})
    save_json_production_document(project_id, document)
    return load_json_production_document(project_id)


def _shot_or_404(document: JsonProductionDocument, shot_id: str) -> JsonProductionShot:
    for shot in document.shots:
        if shot.id == shot_id:
            return shot
    raise HTTPException(404, "Shot not found")


async def _read_ordered_uploads(
    uploads: list[UploadFile],
    *,
    allowed: set[str],
    field: str,
) -> list[tuple[str, bytes]]:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    payloads: list[tuple[str, bytes]] = []
    for index, upload in enumerate(uploads):
        filename = upload.filename or f"{field}_{index}"
        ext = Path(filename).suffix.lower()
        if ext not in allowed:
            raise HTTPException(400, f"{field}: unsupported file type {ext or '(none)'}")
        data = await upload.read()
        if len(data) > max_bytes:
            raise HTTPException(
                400, f"{field}: file exceeds {settings.max_upload_mb}MB"
            )
        if not data:
            raise HTTPException(400, f"{field}: empty file")
        payloads.append((filename, data))
    return payloads


AssetKind = Literal["picture", "audio"]


def _asset_kind(value: str) -> AssetKind:
    kind = value.strip().lower()
    if kind not in {"picture", "audio"}:
        raise HTTPException(400, f"Unsupported asset kind: {value}")
    return kind


_PICTURE_KINDS = {
    "actor": "actors",
    "costume": "costumes",
    "scene": "scenes",
    "prop": "props",
    "layout": "layouts",
}
_PICTURE_KIND_SEARCH = ("actors", "costumes", "scenes", "props", "layouts")


def _declared_slot(
    shot: JsonProductionShot, kind: AssetKind, index: int
) -> JsonProductionPicture | JsonProductionAudio | None:
    slots = shot.pictures if kind == "picture" else shot.audio
    return next((slot for slot in slots if slot.index == index), None)


def _load_picture_asset(asset_id: str, role: str):
    kind = _PICTURE_KINDS.get(role)
    if kind:
        asset = load_asset(kind, asset_id)
        if asset is not None:
            return asset
    for candidate_kind in _PICTURE_KIND_SEARCH:
        asset = load_asset(candidate_kind, asset_id)
        if asset is not None:
            return asset
    return None


def _linked_picture_bytes(
    project_id: str, slot: JsonProductionPicture
) -> tuple[str, bytes]:
    """Resolve a library-linked Picture slot to its real bytes."""
    if not slot.asset_id:
        raise HTTPException(400, f"Picture {slot.index} is not library-linked")
    asset = _load_picture_asset(slot.asset_id, slot.role.value)
    if asset is None:
        raise HTTPException(
            400,
            f"Picture {slot.index} links to a missing library asset: {slot.asset_id}",
        )
    if asset.project_id and asset.project_id != project_id:
        raise HTTPException(
            400,
            f"Picture {slot.index} asset belongs to another project: {slot.asset_id}",
        )
    hit = resolve_asset_image(asset, role=slot.role.value, file_key=slot.file_key)
    if hit is None:
        raise HTTPException(
            400,
            f"Picture {slot.index} library asset has no usable image: {slot.asset_id}",
        )
    name, data, _key = hit
    return name, data


def _linked_audio_bytes(
    project_id: str, slot: JsonProductionAudio
) -> tuple[str, bytes]:
    """Resolve a library-linked Audio slot to its real voice reference bytes."""
    if not slot.asset_id:
        raise HTTPException(400, f"Audio {slot.index} is not library-linked")
    asset = load_asset("voices", slot.asset_id)
    if asset is None or asset.kind != "voices":
        raise HTTPException(
            400,
            f"Audio {slot.index} links to a missing Voice asset: {slot.asset_id}",
        )
    if asset.project_id and asset.project_id != project_id:
        raise HTTPException(
            400,
            f"Audio {slot.index} asset belongs to another project: {slot.asset_id}",
        )
    file_key = slot.file_key or "reference"
    filename = (asset.files or {}).get(file_key)
    if not filename:
        raise HTTPException(
            400,
            f"Audio {slot.index} Voice asset is missing file key "
            f"{file_key!r}: {slot.asset_id}",
        )
    path = asset_dir("voices", slot.asset_id, project_id=asset.project_id) / filename
    if not path.is_file():
        raise HTTPException(
            400,
            f"Audio {slot.index} Voice reference file not found: "
            f"{slot.asset_id}/{filename}",
        )
    return filename, path.read_bytes()


@router.get(
    "/projects/{project_id}/production-storyboard/assets",
    response_model=list[JsonProductionStoredAsset],
)
async def get_json_production_assets(
    project_id: str,
) -> list[JsonProductionStoredAsset]:
    _require_json_project(project_id)
    document = load_json_production_document(project_id)
    return list_json_production_assets(project_id, document)


@router.put(
    "/projects/{project_id}/production-storyboard/shots/{shot_id}/assets/{kind}/{index}",
    response_model=JsonProductionStoredAsset,
)
async def put_json_production_asset(
    project_id: str,
    shot_id: str,
    kind: str,
    index: int,
    file: Annotated[UploadFile, File()],
) -> JsonProductionStoredAsset:
    _require_json_project(project_id)
    document = load_json_production_document(project_id)
    shot = _shot_or_404(document, shot_id)
    selected_kind = _asset_kind(kind)
    slot = _declared_slot(shot, selected_kind, index)
    if slot is None:
        raise HTTPException(
            400, f"{selected_kind.title()} {index} is not declared for shot {shot_id}"
        )
    if slot.asset_id:
        raise HTTPException(
            400,
            f"{selected_kind.title()} {index} is linked to library asset "
            f"{slot.asset_id}; clear the asset link to upload a custom file",
        )
    allowed = ALLOWED_IMAGE_EXT if selected_kind == "picture" else ALLOWED_AUDIO_EXT
    payloads = await _read_ordered_uploads([file], allowed=allowed, field=selected_kind)
    filename, data = payloads[0]
    try:
        return save_json_production_asset(
            project_id,
            shot,
            selected_kind,
            index,
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            data=data,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete(
    "/projects/{project_id}/production-storyboard/shots/{shot_id}/assets/{kind}/{index}",
    status_code=204,
)
async def clear_json_production_asset(
    project_id: str, shot_id: str, kind: str, index: int
) -> Response:
    _require_json_project(project_id)
    document = load_json_production_document(project_id)
    _shot_or_404(document, shot_id)
    selected_kind = _asset_kind(kind)
    delete_json_production_asset(project_id, shot_id, selected_kind, index)
    return Response(status_code=204)


@router.post(
    "/projects/{project_id}/production-storyboard/shots/{shot_id}/submit",
    response_model=H3Ref2VaJobResponse,
)
async def submit_json_shot(
    project_id: str,
    shot_id: str,
    revision: int = Form(...),
    h3_provider: str | None = Form(None),
    pictures: list[UploadFile] = File(default_factory=list),
    audios: list[UploadFile] = File(default_factory=list),
) -> H3Ref2VaJobResponse:
    _require_json_project(project_id)
    document = load_json_production_document(project_id)
    shot = _shot_or_404(document, shot_id)
    if revision != document.revision:
        raise HTTPException(409, "stale production storyboard revision")

    selected_h3_provider = str(
        h3_provider or settings.h3_provider or "local"
    ).strip().lower()
    if selected_h3_provider not in {"local", "minimax"}:
        raise HTTPException(
            400, f"Unsupported H3 provider: {selected_h3_provider}"
        )
    if selected_h3_provider == "minimax" and not str(
        settings.h3_minimax_api_key or ""
    ).strip():
        raise HTTPException(400, "MiniMax H3 API key is not configured")

    prompt_text = ensure_global_prompt_in_h3(
        compose_h3_prompt(shot.prompt),
        effective_global_prompt(project_id),
    )
    try:
        validate_h3_prompt(
            prompt_text,
            list(shot.dialogue),
            required_picture_indices=range(1, len(shot.pictures) + 1),
            submitted_picture_indices=range(1, len(shot.pictures) + 1),
            audio_count=len(shot.audio),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if pictures:
        if len(pictures) != len(shot.pictures):
            raise HTTPException(
                400,
                f"expected {len(shot.pictures)} pictures, got {len(pictures)}",
            )
        upload_payloads = await _read_ordered_uploads(
            pictures, allowed=ALLOWED_IMAGE_EXT, field="pictures"
        )
    else:
        upload_payloads = None
    picture_payloads: list[tuple[str, bytes]] = []
    for position, slot in enumerate(shot.pictures):
        if slot.asset_id:
            if upload_payloads is not None:
                raise HTTPException(
                    400,
                    f"Picture {slot.index} is linked to library asset "
                    f"{slot.asset_id}; remove the uploaded file or clear the link",
                )
            picture_payloads.append(_linked_picture_bytes(project_id, slot))
        elif upload_payloads is not None:
            picture_payloads.append(upload_payloads[position])
        else:
            loaded = load_json_production_asset(
                project_id, shot, "picture", slot.index
            )
            if loaded is None:
                raise HTTPException(400, f"missing staged file for Picture {slot.index}")
            asset, path = loaded
            picture_payloads.append((asset.filename, path.read_bytes()))

    if audios:
        if len(audios) != len(shot.audio):
            raise HTTPException(
                400,
                f"expected {len(shot.audio)} audios, got {len(audios)}",
            )
        audio_uploads = await _read_ordered_uploads(
            audios, allowed=ALLOWED_AUDIO_EXT, field="audios"
        )
    else:
        audio_uploads = None
    audio_payloads: list[tuple[str, bytes]] = []
    for position, slot in enumerate(shot.audio):
        if slot.asset_id:
            if audio_uploads is not None:
                raise HTTPException(
                    400,
                    f"Audio {slot.index} is linked to library asset "
                    f"{slot.asset_id}; remove the uploaded file or clear the link",
                )
            audio_payloads.append(_linked_audio_bytes(project_id, slot))
        elif audio_uploads is not None:
            audio_payloads.append(audio_uploads[position])
        else:
            loaded = load_json_production_asset(project_id, shot, "audio", slot.index)
            if loaded is None:
                raise HTTPException(400, f"missing staged file for Audio {slot.index}")
            asset, path = loaded
            audio_payloads.append((asset.filename, path.read_bytes()))

    try:
        frames = frames_for_seconds(shot.duration_s)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    landscape = document.aspect_ratio == "16:9"
    images: dict[str, tuple[str, bytes]] = {}
    image_keys = [f"ref_{i}" for i in range(len(picture_payloads))]
    audio_keys = [f"ref_audio_{i}" for i in range(len(audio_payloads))]
    for key, payload in zip(image_keys, picture_payloads):
        images[key] = payload
    for key, payload in zip(audio_keys, audio_payloads):
        images[key] = payload

    job = create_job(
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        name=f"h3:{shot.title}",
        notes=shot.script_beat,
        params={
            "h3_provider": selected_h3_provider,
            "prompt": prompt_text,
            "dialogue": list(shot.dialogue),
            "frames": frames,
            "duration_s": shot.duration_s,
            "image_keys": image_keys,
            "audio_keys": audio_keys,
            "native_audio_key": None,
            "width": 864 if landscape else 480,
            "height": 480 if landscape else 864,
            "project_id": project_id,
            "json_shot_id": shot.id,
            "json_storyboard_revision": document.revision,
            "ref_roles": [item.role.value for item in shot.pictures],
            "output_prefix": f"director-studio/{project_id}/{shot.id}/h3",
        },
        project_id=project_id,
    )

    try:
        job = await start_pipeline_job(job, images=images or None)
    except Exception as exc:
        raise HTTPException(503, f"Failed to start H3 job: {exc}") from exc

    return H3Ref2VaJobResponse.from_job(job)
