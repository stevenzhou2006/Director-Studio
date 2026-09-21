"""Concatenate every Shot's finished H3 clip into one video file with ffmpeg."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from ..projects.store import list_shots, load_project
from .clip_generations import (
    ClipGenerationError,
    ResolvedClip,
    resolve_latest_succeeded_clip,
)

_SAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")
_DEFAULT_STEM = "final"


def concatenate_project_shots(
    *,
    project_id: str,
    output_name: str | None = None,
    output_kind: Literal["enhanced", "raw"] | None = None,
    reencode: bool = False,
) -> dict[str, Any]:
    """Join every Shot's newest succeeded H3 clip, in Shot order, into one file.

    Stream-copies when the clips are cut-compatible and falls back to a full
    filter re-encode otherwise. Returns the absolute output path on this host.
    """
    project = load_project(project_id)
    if project is None:
        raise ClipGenerationError(f"project not found: {project_id}")

    shots = list_shots(project_id)
    if not shots:
        raise ValueError("project has no shots to concatenate")

    resolved: list[tuple[str, str, ResolvedClip]] = []
    missing: list[str] = []
    for shot in shots:
        try:
            clip = resolve_latest_succeeded_clip(
                project_id=project_id,
                source_shot_id=shot.id,
                output_kind=output_kind,
            )
        except ClipGenerationError as exc:
            missing.append(f"{shot.title} ({shot.id}): {exc}")
            continue
        resolved.append((shot.id, shot.title, clip))

    if missing:
        raise ClipGenerationError(
            "cannot concatenate: no succeeded H3 clip for "
            + "; ".join(missing)
        )

    out_path = _output_path(project_id, output_name=output_name, project_name=project.name)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    method = "reencode"
    if not reencode:
        try:
            _concat_stream_copy([clip.path for _sid, _title, clip in resolved], out_path)
            method = "copy"
        except ValueError:
            method = "reencode"
    if method == "reencode":
        _concat_reencode([clip.path for _sid, _title, clip in resolved], out_path)

    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise ValueError("ffmpeg produced no output file")

    return {
        "ok": True,
        "output_path": str(out_path.resolve()),
        "filename": out_path.name,
        "url": (
            f"/api/files/projects/{project_id}/renders/{out_path.name}"
            f"?v={_artifact_version(out_path)}"
        ),
        "method": method,
        "clip_count": len(resolved),
        "duration_s": _probe_duration(out_path),
        "clips": [
            {
                "shot_id": shot_id,
                "title": title,
                "job_id": clip.source_job_id,
                "generation": clip.source_generation,
                "output_kind": clip.output_kind,
                "source_path": str(clip.path.resolve()),
            }
            for shot_id, title, clip in resolved
        ],
    }


def _output_path(project_id: str, *, output_name: str | None, project_name: str) -> Path:
    from ..paths import project_root

    raw = (output_name or "").strip()
    if raw:
        stem = Path(raw).stem or _DEFAULT_STEM
    else:
        stem = _SAFE_STEM.sub("_", (project_name or "").strip()).strip("._-") or _DEFAULT_STEM
        stem = f"{stem}_final"
    stem = _SAFE_STEM.sub("_", stem).strip("._-") or _DEFAULT_STEM
    return project_root(project_id) / "renders" / f"{stem}.mp4"


def _artifact_version(path: Path) -> str:
    """Cache-busting token: changes whenever the rendered file changes."""
    try:
        stat = path.stat()
    except OSError:
        return "0"
    return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"


def _require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise ValueError(f"{name} is required to concatenate clips")
    return resolved


def _run(command: list[str], *, error: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(error) from exc


def _concat_escape(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _concat_stream_copy(clips: list[Path], out_path: Path) -> None:
    """Fast path: concat demuxer with stream copy. Raises ValueError on failure."""
    ffmpeg = _require_binary("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="ds_concat_") as raw_tmp:
        list_path = Path(raw_tmp) / "clips.txt"
        list_path.write_text(
            "".join(f"file '{_concat_escape(clip)}'\n" for clip in clips),
            encoding="utf-8",
        )
        _run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(out_path),
            ],
            error="stream-copy concat failed",
        )


def _concat_reencode(clips: list[Path], out_path: Path) -> None:
    """Robust path: concat filter with re-encode (audio only when every clip has it)."""
    ffmpeg = _require_binary("ffmpeg")
    has_audio = [_clip_has_audio(clip) for clip in clips]
    all_audio = all(has_audio) and bool(clips)

    command = [ffmpeg, "-y", "-hide_banner", "-v", "error"]
    for clip in clips:
        command.extend(["-i", str(clip)])

    concat_inputs = "".join(
        f"[{index}:v:0]" + (f"[{index}:a:0]" if all_audio else "")
        for index in range(len(clips))
    )
    if all_audio:
        filter_complex = f"{concat_inputs}concat=n={len(clips)}:v=1:a=1[v][a]"
    else:
        filter_complex = f"{concat_inputs}concat=n={len(clips)}:v=1:a=0[v]"

    command.extend(["-filter_complex", filter_complex, "-map", "[v]"])
    if all_audio:
        command.extend(["-map", "[a]", "-c:a", "aac"])
    else:
        command.append("-an")
    command.extend(
        [
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
    )
    _run(command, error="re-encode concat failed")


def _clip_has_audio(path: Path) -> bool:
    try:
        result = _run(
            [
                _require_binary("ffprobe"),
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ],
            error="unable to probe audio streams",
        )
    except ValueError:
        return False
    return bool(result.stdout.strip())


def _probe_duration(path: Path) -> float | None:
    try:
        result = _run(
            [
                _require_binary("ffprobe"),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            error="unable to probe video duration",
        )
        payload = json.loads(result.stdout)
        duration = float((payload.get("format") or {}).get("duration"))
    except (ValueError, TypeError, json.JSONDecodeError, KeyError):
        return None
    return duration if duration > 0 else None
