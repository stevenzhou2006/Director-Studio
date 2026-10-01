"""Deterministic post-H3 finalize: font-layer poem overlay + original audio.

H3 can neither render Chinese glyphs reliably nor keep a locked source
recitation: the official Ref2AV graph treats the voice reference as model
conditioning and regenerates the audio track. This module closes that gap
after a successful H3 job by chaining the ffmpeg-only ``poem_overlay``
pipeline:

- the title / dynasty / author / seal are composited with real calligraphy
  fonts (never drawn by the image model);
- when the shot has an original recitation attached, its exact audio
  replaces the H3-generated track (padded with silence to the clip length);
- when no recitation is attached, the H3-generated audio is kept untouched,
  so H3's native audio generation capability is preserved.

Opt out per shot with ``shot.meta.poem_auto_overlay = False``.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from ...pipelines.poem_overlay import timing
from ..projects.models import Shot
from ..projects.store import load_project, load_shot
from ..schemas import JobRecord, JobStatus, OutputSlot
from . import store

logger = logging.getLogger("director_studio.jobs.poem_finalize")

OVERLAY_PIPELINE_ID = "poem_overlay"

_finalize_tasks: set[asyncio.Task[None]] = set()


def get_poem_dict(shot: Shot) -> dict[str, Any]:
    """Read ``shot.meta['poem']`` without depending on the agents layer."""
    meta = getattr(shot, "meta", None)
    if not isinstance(meta, dict):
        return {}
    poem = meta.get("poem")
    return poem if isinstance(poem, dict) else {}


def _has_poem_identity(shot: Shot) -> bool:
    poem = get_poem_dict(shot)
    return bool(str(poem.get("title") or "").strip()) and bool(
        str(poem.get("author") or "").strip()
    )


def is_first_poem_shot(project_id: str, shot_id: str) -> bool:
    """Return True when ``shot_id`` is the first poem-bearing shot in the project.

    The title card must appear exactly once in the concatenated film, on the
    first shot that actually carries poem title/author metadata. Walking
    ``project.shot_ids`` (the source of truth for order) makes this
    deterministic regardless of the order finalize jobs happen to run in.
    If the project or its shot list cannot be resolved, fall back to showing
    the title (preserves legacy single-shot behaviour).
    """
    project = load_project(project_id)
    if project is None or not project.shot_ids:
        return True
    for candidate_id in project.shot_ids:
        if candidate_id == shot_id:
            return True
        candidate = load_shot(project_id, candidate_id)
        if candidate is not None and _has_poem_identity(candidate):
            return False
    # shot not listed in project.shot_ids: treat as first.
    return True


class PoemMasterFinishError(ValueError):
    """Raised when a poem project cannot be master-finished."""


def is_poem_project(project_id: str) -> bool:
    """True when every shot in the project carries poem title/author + lines."""
    project = load_project(project_id)
    if project is None or not project.shot_ids:
        return False
    for shot_id in project.shot_ids:
        shot = load_shot(project_id, shot_id)
        if shot is None:
            return False
        poem = get_poem_dict(shot)
        lines = poem.get("lines")
        if not _has_poem_identity(shot) or not isinstance(lines, list) or not lines:
            return False
    return True


def build_master_finish_plan(
    project_id: str, clips: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build the master-finish plan from the resolved concat clips.

    ``clips`` entries must carry ``shot_id`` and ``duration_s``. Returns
    ``{"segments": [...], "audio_parts": [(path, duration), ...],
    "total_duration": float}``. Raises :class:`PoemMasterFinishError` if a
    shot lacks a resolvable recitation (the all-shots-must-have-recitation
    policy) or poem meta.
    """
    if not clips:
        raise PoemMasterFinishError("no clips to master-finish")
    segments: list[dict[str, Any]] = []
    audio_parts: list[tuple[Path, float]] = []
    offset = 0.0
    for clip in clips:
        shot_id = str(clip.get("shot_id") or "")
        shot = load_shot(project_id, shot_id) if shot_id else None
        if shot is None:
            raise PoemMasterFinishError(f"cannot resolve shot for clip {clip}")
        poem = get_poem_dict(shot)
        if not _has_poem_identity(shot):
            raise PoemMasterFinishError(
                f"shot {shot.title} ({shot.id}) has no poem title/author"
            )
        raw_lines = poem.get("lines")
        if not isinstance(raw_lines, list) or not raw_lines:
            raise PoemMasterFinishError(f"shot {shot.title} ({shot.id}) has no lines")
        duration = float(clip.get("duration_s") or shot.duration_s or 0.0)
        if duration <= 0:
            raise PoemMasterFinishError(
                f"shot {shot.title} ({shot.id}) has no usable clip duration"
            )
        try:
            audio_path, _lead = timing.resolve_recitation_audio(shot)
        except timing.PoemTimingError as exc:
            raise PoemMasterFinishError(
                f"shot {shot.title} ({shot.id}) has no resolvable recitation: {exc}"
            ) from exc
        lines = [entry for entry in raw_lines if isinstance(entry, dict)]
        starts = _resolve_line_starts(lines, audio_path, duration)
        timed = [
            {"text": str(entry.get("text") or ""), "start_s": start}
            for entry, start in zip(lines, starts)
        ]
        segments.append({"offset_s": round(offset, 3), "lines": timed})
        audio_parts.append((audio_path, duration))
        offset += duration
    return {
        "segments": segments,
        "audio_parts": audio_parts,
        "total_duration": round(offset, 3),
    }


def build_unified_recitation(
    parts: list[tuple[Path, float]], out_path: Path, *, target_lufs: float = -16.0
) -> None:
    """Concatenate per-shot recitations into one continuous track.

    Each recitation is loudness-normalized (EBU R128) to a common target before
    being trimmed/padded to its segment duration, so separately generated TTS
    takes do not play at different volumes across the film.
    """
    if not parts:
        raise PoemMasterFinishError("no recitation parts to unify")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise PoemMasterFinishError("ffmpeg is required to build the unified recitation")
    inputs: list[str] = []
    filters: list[str] = []
    for index, (audio, duration) in enumerate(parts):
        if not Path(audio).is_file():
            raise PoemMasterFinishError(f"recitation file missing: {audio}")
        inputs += ["-i", str(audio)]
        filters.append(
            f"[{index}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11,"
            f"apad=whole_dur={duration:.3f}[a{index}]"
        )
    concat_in = "".join(f"[a{i}]" for i in range(len(parts)))
    filters.append(f"{concat_in}concat=n={len(parts)}:v=0:a=1[out]")
    command = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, check=False, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise PoemMasterFinishError(
            f"unified recitation failed: {result.stderr.strip()[-800:]}"
        )


def _slot_file(slot: OutputSlot | None, job: JobRecord) -> Path | None:
    if slot is None:
        return None
    if slot.path and Path(slot.path).is_file():
        return Path(slot.path)
    name = slot.filename or (Path(slot.path).name if slot.path else "")
    if not name:
        return None
    candidate = store.job_dir(job.id, project_id=job.project_id) / "outputs" / name
    return candidate if candidate.is_file() else None


def poem_finalize_skip_reason(shot: Shot, h3_job: JobRecord) -> str | None:
    """Return why this H3 success must not auto-finalize, or ``None`` if eligible."""
    if h3_job.status != JobStatus.succeeded:
        return "h3 job is not succeeded"
    poem = get_poem_dict(shot)
    title = str(poem.get("title") or "").strip()
    author = str(poem.get("author") or "").strip()
    if not title or not author:
        return "shot has no poem title/author metadata"
    lines = poem.get("lines")
    if not isinstance(lines, list) or not lines:
        return "poem has no lines to overlay"
    if (shot.meta or {}).get("poem_auto_overlay") is False:
        return "auto overlay disabled on this shot"
    if (h3_job.params or {}).get("poem_finalized"):
        return "h3 job already finalized"
    if _slot_file((h3_job.outputs or {}).get("video"), h3_job) is None:
        return "h3 job has no materialized video output"
    for existing in store.list_jobs(
        limit=None,
        pipeline_id=OVERLAY_PIPELINE_ID,
        project_id=h3_job.project_id,
    ):
        if (existing.params or {}).get("source_h3_job_id") != h3_job.id:
            continue
        # A failed/cancelled finalize must not block a retry.
        if existing.status in {JobStatus.failed, JobStatus.cancelled}:
            continue
        return f"finalize overlay already exists: {existing.id}"
    return None


def _resolve_line_starts(
    lines: list[dict[str, Any]],
    audio_path: Path | None,
    duration_s: float,
) -> list[float]:
    """Resolve one start second per line: explicit > ASR > even spread.

    Even spread only applies when there is no recitation audio to sync
    against; a recitation shot never gets guessed timings.
    """
    explicit = [entry.get("start_s") for entry in lines]
    if all(value is not None for value in explicit):
        return [float(value) for value in explicit]
    if audio_path is not None:
        return timing.derive_line_starts(
            [str(entry.get("text") or "") for entry in lines],
            audio_path=audio_path,
        )
    count = len(lines)
    span = max(float(duration_s), float(count))
    step = span / count
    return [round(index * step, 2) for index in range(count)]


async def run_poem_finalize(h3_job: JobRecord, shot: Shot) -> None:
    """Queue the font-layer overlay (and original-audio swap) for one H3 clip."""
    reason = poem_finalize_skip_reason(shot, h3_job)
    if reason is not None:
        logger.info(
            "poem finalize skipped for h3 job %s: %s", h3_job.id, reason
        )
        return

    poem = get_poem_dict(shot)
    lines = [entry for entry in poem.get("lines") or [] if isinstance(entry, dict)]
    video_path = _slot_file((h3_job.outputs or {}).get("video"), h3_job)
    if video_path is None:
        return

    audio_path: Path | None = None
    try:
        audio_path, _lead = await asyncio.to_thread(timing.resolve_recitation_audio, shot)
    except timing.PoemTimingError:
        audio_path = None
    replace_audio = audio_path is not None

    try:
        starts = await asyncio.to_thread(
            _resolve_line_starts, lines, audio_path, float(shot.duration_s or 0.0)
        )
    except timing.PoemTimingError as exc:
        logger.warning(
            "poem finalize skipped for h3 job %s: line timing failed: %s",
            h3_job.id,
            exc,
        )
        return

    timed_lines = [
        {"text": str(entry.get("text") or ""), "start_s": start}
        for entry, start in zip(lines, starts)
    ]
    show_title = is_first_poem_shot(shot.project_id, shot.id)
    job = store.create_job(
        pipeline_id=OVERLAY_PIPELINE_ID,
        asset_kind="productions",
        name=f"finalize: {shot.title}",
        notes=(
            f"auto-finalize of {h3_job.id}: "
            + ("font-layer title card + " if show_title else "subtitle columns only; ")
            + ("original recitation audio" if replace_audio else "H3 native audio kept")
        ),
        params={
            "title": poem.get("title"),
            "author": poem.get("author"),
            "dynasty": poem.get("dynasty") or "唐",
            "seal": poem.get("seal") or "狸",
            "lines": timed_lines,
            "output_name": f"final_{shot.id}",
            "replace_audio": replace_audio,
            "show_title": show_title,
            "shot_id": shot.id,
            "source_h3_job_id": h3_job.id,
            "project_id": shot.project_id,
        },
        project_id=shot.project_id,
    )
    images: dict[str, tuple[str, bytes]] = {
        "video": (video_path.name, await asyncio.to_thread(video_path.read_bytes)),
    }
    if audio_path is not None:
        images["audio"] = (
            audio_path.name,
            await asyncio.to_thread(audio_path.read_bytes),
        )

    from .runner import start_pipeline_job

    await start_pipeline_job(job, images=images)
    logger.info(
        "poem finalize overlay queued: %s for h3 job %s (replace_audio=%s)",
        job.id,
        h3_job.id,
        replace_audio,
    )


async def _guarded_finalize(h3_job: JobRecord, shot: Shot) -> None:
    try:
        await run_poem_finalize(h3_job, shot)
    except Exception:
        logger.exception("poem finalize failed for h3 job %s", h3_job.id)


def schedule_poem_finalize(h3_job: JobRecord, shot: Shot) -> None:
    """Fire-and-forget the finalize from sync (shot_sync) contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        task = loop.create_task(_guarded_finalize(h3_job, shot))
        _finalize_tasks.add(task)
        task.add_done_callback(_finalize_tasks.discard)
    else:
        threading.Thread(
            target=lambda: asyncio.run(_guarded_finalize(h3_job, shot)),
            daemon=True,
        ).start()


def first_poem_meta(project_id: str) -> dict[str, Any]:
    """The poem identity carried by the project's first poem-bearing shot."""
    from ..projects.store import list_shots

    for shot in list_shots(project_id):
        poem = get_poem_dict(shot)
        if poem.get("title") and poem.get("author"):
            return poem
    return {}


async def run_master_finish(
    project_id: str,
    base_result: dict[str, Any],
    output_name: str | None,
    *,
    watermark: str = "",
) -> dict[str, Any]:
    """Master-level finish of a concatenated base film.

    Builds the loudness-normalized unified recitation, then composites the
    title card once + per-segment poem columns + the watermark in a single
    overlay pass, and returns the finished result (output path/url + overlay
    meta). Raises :class:`PoemMasterFinishError` if the project cannot be
    finished (missing recitation, poem meta, or a failed render). Shared by
    the Director ``concatenate_shots`` tool and the REST concatenate
    endpoint so the UI button produces the same finished film.
    """
    import tempfile

    plan = build_master_finish_plan(project_id, base_result["clips"])
    base_path = Path(base_result["output_path"])
    with tempfile.TemporaryDirectory(prefix="ds-master-") as tmp:
        unified = Path(tmp) / "recitation.m4a"
        await asyncio.to_thread(build_unified_recitation, plan["audio_parts"], unified)
        poem = first_poem_meta(project_id)
        job = store.create_job(
            pipeline_id=OVERLAY_PIPELINE_ID,
            asset_kind="productions",
            name=f"master finish: {output_name or project_id}",
            notes=(
                f"master-level finish of {base_result['clip_count']} shot(s): "
                "title card once + per-segment poem columns + unified "
                "recitation + "
                + (f"watermark {watermark}" if watermark else "no watermark")
            ),
            params={
                "title": poem.get("title"),
                "author": poem.get("author"),
                "dynasty": poem.get("dynasty") or "唐",
                "seal": poem.get("seal") or "狸",
                "segments": plan["segments"],
                "output_name": output_name or "final",
                "show_title": True,
                "watermark": watermark or "",
                "project_id": project_id,
                "master_finish": True,
                "source_base_path": str(base_path),
            },
            project_id=project_id,
        )
        from .runner import await_pipeline_job, start_pipeline_job

        await start_pipeline_job(
            job,
            images={
                "video": (
                    base_path.name,
                    await asyncio.to_thread(base_path.read_bytes),
                ),
                "audio": (unified.name, await asyncio.to_thread(unified.read_bytes)),
            },
        )
        terminal = await await_pipeline_job(job.id)
    if terminal is None or terminal.status != JobStatus.succeeded:
        err = (terminal.error if terminal else "job disappeared") or "master finish failed"
        raise PoemMasterFinishError(err)
    video_slot = (terminal.outputs or {}).get("video")
    meta = (terminal.params or {}).get("overlay") or {}
    return {
        "job_id": terminal.id,
        "output_path": video_slot.path if video_slot else None,
        "filename": video_slot.filename if video_slot else None,
        "url": video_slot.url if video_slot else None,
        "overlay": meta,
    }
