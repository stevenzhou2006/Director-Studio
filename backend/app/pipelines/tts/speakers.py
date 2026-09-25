"""Per-project saved-speaker registry for Qwen3-TTS voice cloning.

A *speaker* is a reusable voice identity registered from a short reference
clip. Metadata lives in the project tree::

    data/projects/<prj>/speakers/<spk_id>.json
    data/projects/<prj>/speakers/<spk_id>/reference.wav   (playback copy)

The engine-side trio produced by ``FB_Qwen3TTSSaveVoice`` lives in the
ComfyUI ``models/qwen-tts/voices`` directory under the collision-proof
slug ``spk_<spk_id>``:

    spk_<spk_id>.qvp    pre-computed clone features (fast-load)
    spk_<spk_id>.json   ref_text metadata (typed once, auto-loaded)
    spk_<spk_id>.wav    reference audio

The stored ``ref_text`` must match what is spoken in the reference audio;
``FB_Qwen3TTSLoadSpeaker`` returns it with the features so speech jobs
never need it re-entered.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from ...config import settings
from ...core.paths import project_root

SPEAKER_STATUS_REGISTERING = "registering"
SPEAKER_STATUS_READY = "ready"
SPEAKER_STATUS_FAILED = "failed"

_REF_MIN_S = 2.0
_REF_MAX_S = 30.0
_REF_RECOMMENDED_MIN_S = 5.0
_REF_RECOMMENDED_MAX_S = 15.0
_ALLOWED_EXT = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}


def speakers_dir(project_id: str) -> Path:
    d = project_root(project_id) / "speakers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _speaker_json_path(project_id: str, spk_id: str) -> Path:
    return speakers_dir(project_id) / f"{spk_id}.json"


def _speaker_folder(project_id: str, spk_id: str) -> Path:
    d = speakers_dir(project_id) / spk_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_speaker_id() -> str:
    return f"spk_{uuid.uuid4().hex[:12]}"


def slug_for(spk_id: str) -> str:
    """ComfyUI voices-dir basename. The id prefix keeps projects from colliding."""
    return spk_id


def speaker_wav_name(spk_id: str) -> str:
    """The wav filename FB_Qwen3TTSLoadSpeaker selects by."""
    return f"{slug_for(spk_id)}.wav"


def _write(speaker: dict[str, Any]) -> None:
    path = _speaker_json_path(str(speaker["project_id"]), str(speaker["id"]))
    path.write_text(
        json.dumps(speaker, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_speaker(project_id: str, spk_id: str) -> dict[str, Any] | None:
    path = _speaker_json_path(project_id, spk_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def resolve_speaker(project_id: str, ref: str) -> dict[str, Any] | None:
    """Resolve a speaker by exact id or exact/case-insensitive name."""
    ref = (ref or "").strip()
    if not ref:
        return None
    exact = get_speaker(project_id, ref)
    if exact is not None:
        return exact
    lowered = ref.lower()
    for speaker in list_speakers(project_id):
        if str(speaker.get("name", "")).strip().lower() == lowered:
            return speaker
    return None


def engine_files_status(spk_id: str) -> dict[str, bool]:
    voices = Path(settings.qwen_tts_voices_dir)
    slug = slug_for(spk_id)
    return {
        "qvp": (voices / f"{slug}.qvp").is_file(),
        "json": (voices / f"{slug}.json").is_file(),
        "wav": (voices / f"{slug}.wav").is_file(),
    }


def speaker_is_ready(spk_id: str) -> bool:
    status = engine_files_status(spk_id)
    return bool(status["qvp"] and status["wav"])


def _decorate(project_id: str, speaker: dict[str, Any]) -> dict[str, Any]:
    out = dict(speaker)
    files = engine_files_status(str(speaker["id"]))
    out["engine_files"] = files
    out["engine_ready"] = bool(files["qvp"] and files["wav"])
    if (
        out.get("status") == SPEAKER_STATUS_REGISTERING
        and out["engine_ready"]
    ):
        out["status"] = SPEAKER_STATUS_READY
    preview = speakers_dir(project_id) / str(speaker["id"]) / "reference.wav"
    if preview.is_file():
        out["preview_url"] = (
            f"/api/files/projects/{project_id}/speakers/"
            f"{speaker['id']}/reference.wav"
        )
    else:
        out["preview_url"] = None
    return out


def list_speakers(project_id: str) -> list[dict[str, Any]]:
    root = speakers_dir(project_id)
    speakers: list[dict[str, Any]] = []
    for path in sorted(root.glob("spk_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("id"):
            speakers.append(_decorate(project_id, data))
    speakers.sort(key=lambda s: str(s.get("created_at") or ""), reverse=True)
    return speakers


def create_speaker(
    *,
    project_id: str,
    name: str,
    ref_text: str,
    ref_audio_bytes: bytes,
    source_filename: str,
    source_asset_id: str | None = None,
) -> dict[str, Any]:
    """Create a speaker record + local reference copy (engine files pending)."""
    name = (name or "").strip()
    ref_text = (ref_text or "").strip()
    if not name:
        raise ValueError("speaker name is required")
    if not ref_text:
        raise ValueError(
            "ref_text is required: enter exactly what is spoken in the "
            "reference audio. It is saved with the voice so it never has to "
            "be typed again."
        )
    if not ref_audio_bytes:
        raise ValueError("reference audio is required")
    ext = Path(source_filename or "reference.wav").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise ValueError(
            f"unsupported reference audio type {ext!r}; "
            f"allowed: {', '.join(sorted(_ALLOWED_EXT))}"
        )
    duration_s = _probe_duration_bytes(ref_audio_bytes)
    if duration_s is not None and (
        duration_s < _REF_MIN_S or duration_s > _REF_MAX_S
    ):
        raise ValueError(
            f"reference audio is {duration_s:.1f}s; keep it between "
            f"{_REF_MIN_S:.0f} and {_REF_MAX_S:.0f} seconds "
            f"({_REF_RECOMMENDED_MIN_S:.0f}-{_REF_RECOMMENDED_MAX_S:.0f}s recommended)"
        )

    spk_id = new_speaker_id()
    folder = _speaker_folder(project_id, spk_id)
    stored_ref = folder / f"source{ext}"
    stored_ref.write_bytes(ref_audio_bytes)
    _transcode_reference(stored_ref, folder / "reference.wav")

    speaker: dict[str, Any] = {
        "id": spk_id,
        "project_id": project_id,
        "name": name,
        "slug": slug_for(spk_id),
        "ref_text": ref_text,
        "source": f"upload:{source_filename}" if source_filename else "upload",
        "source_asset_id": source_asset_id,
        "duration_s": duration_s,
        "status": SPEAKER_STATUS_REGISTERING,
        "register_job_id": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write(speaker)
    return _decorate(project_id, speaker)


def attach_register_job(project_id: str, spk_id: str, job_id: str) -> dict[str, Any]:
    speaker = get_speaker(project_id, spk_id)
    if speaker is None:
        raise ValueError(f"speaker not found: {spk_id}")
    speaker["register_job_id"] = job_id
    _write(speaker)
    return _decorate(project_id, speaker)


def set_status(
    project_id: str, spk_id: str, status: str, *, error: str | None = None
) -> dict[str, Any]:
    speaker = get_speaker(project_id, spk_id)
    if speaker is None:
        raise ValueError(f"speaker not found: {spk_id}")
    speaker["status"] = status
    if error:
        speaker["error"] = error
    else:
        speaker.pop("error", None)
    _write(speaker)
    return _decorate(project_id, speaker)


def delete_speaker(project_id: str, spk_id: str) -> bool:
    speaker = get_speaker(project_id, spk_id)
    if speaker is None:
        return False
    folder = speakers_dir(project_id) / spk_id
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    _speaker_json_path(project_id, spk_id).unlink(missing_ok=True)
    voices = Path(settings.qwen_tts_voices_dir)
    slug = slug_for(spk_id)
    for suffix in (".qvp", ".json", ".wav"):
        (voices / f"{slug}{suffix}").unlink(missing_ok=True)
    return True


def _probe_duration_bytes(data: bytes) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                tmp.name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    try:
        return float(result.stdout.strip())
    except (TypeError, ValueError):
        return None


def _transcode_reference(source: Path, destination: Path) -> None:
    """Normalize the reference to wav for browser playback (best effort)."""
    if not shutil.which("ffmpeg"):
        shutil.copyfile(source, destination)
        return
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "24000",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not destination.is_file():
        shutil.copyfile(source, destination)
