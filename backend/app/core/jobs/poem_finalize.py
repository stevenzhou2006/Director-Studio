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
import threading
from pathlib import Path
from typing import Any

from ...pipelines.poem_overlay import timing
from ..projects.models import Shot
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
    job = store.create_job(
        pipeline_id=OVERLAY_PIPELINE_ID,
        asset_kind="productions",
        name=f"finalize: {shot.title}",
        notes=(
            f"auto-finalize of {h3_job.id}: font-layer title card + "
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
