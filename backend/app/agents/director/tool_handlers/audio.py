"""Speech (TTS) and poem-subtitle overlay tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ....core.library.audio import probe_audio
from ....core.media.clip_generations import (
    ClipGenerationError,
    resolve_latest_succeeded_clip,
    resolve_source_clip,
)
from ....core.schemas import JobRecord, JobStatus
from ....pipelines.tts import workflow as tts_workflow

_TTS_TOOL_NAMES = frozenset({"generate_tts_audio", "generate_speech", "tts"})
_OVERLAY_TOOL_NAMES = frozenset(
    {"overlay_poem_subtitles", "poem_overlay", "overlay_poem"}
)


async def handle_audio_tool(
    *,
    name: str,
    args: dict[str, Any],
    project_id: str,
    runtime: Any,
    actions: list[str],
    notes: list[str],
    result_payloads: list[dict[str, Any]] | None,
    images: list[Any] | None,
) -> bool:
    """Handle speech and poem-overlay tools; return whether the name matched."""
    if name in _TTS_TOOL_NAMES:
        await _handle_tts(
            args=args,
            project_id=project_id,
            runtime=runtime,
            actions=actions,
            notes=notes,
            result_payloads=result_payloads,
        )
        return True
    if name in _OVERLAY_TOOL_NAMES:
        await _handle_overlay(
            args=args,
            project_id=project_id,
            runtime=runtime,
            actions=actions,
            notes=notes,
            result_payloads=result_payloads,
        )
        return True
    return False


async def _handle_tts(
    *,
    args: dict[str, Any],
    project_id: str,
    runtime: Any,
    actions: list[str],
    notes: list[str],
    result_payloads: list[dict[str, Any]] | None,
) -> None:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValueError("generate_tts_audio requires text")
    style = str(args.get("style") or "longchang-girl").strip().lower()
    if style not in tts_workflow.STYLES:
        raise ValueError(
            "generate_tts_audio style must be one of "
            + ", ".join(tts_workflow.STYLES)
        )
    name_value = str(args.get("name") or "").strip() or f"Speech · {text[:16]}"

    params: dict[str, Any] = {
        "text": text,
        "style": style,
        "respell": str(args.get("respell") or "").strip(),
        "age": str(args.get("age") or workflow_default("age")).strip(),
        "rhyme": str(args.get("rhyme") or workflow_default("rhyme")).strip(),
        "emotion": str(args.get("emotion") or workflow_default("emotion")).strip(),
        "speaker": str(args.get("speaker") or tts_workflow.DEFAULT_ERIC_SPEAKER).strip(),
        "instruct": str(args.get("instruct") or "").strip(),
        "model_choice": str(args.get("model_choice") or "1.7B").strip(),
        "lead_silence_s": _optional_float(args.get("lead_silence_s"), default=0.0),
        "project_id": project_id,
    }
    seed = args.get("seed")
    try:
        seed_value = int(seed) if seed is not None else None
    except (TypeError, ValueError):
        raise ValueError("generate_tts_audio seed must be an integer") from None

    job = runtime.create_job(
        pipeline_id="tts",
        asset_kind="voices",
        name=name_value,
        notes=" ".join(text.split())[:400],
        params=params,
        seed=seed_value,
        project_id=project_id,
    )
    await runtime.start_pipeline_job(job, images={})
    terminal = await runtime.await_pipeline_job(job.id)
    if terminal is None:
        raise ValueError(f"Speech job disappeared: {job.id}")
    if terminal.status != JobStatus.succeeded:
        raise ValueError(
            str(terminal.error or f"Speech job status is {terminal.status.value}")
        )

    audio_slot = terminal.outputs.get("audio")
    if audio_slot is None or not (audio_slot.url or audio_slot.path):
        raise ValueError("Speech job completed without an audio output")
    padded_slot = terminal.outputs.get("audio_padded")

    duration_s: float | None = None
    if audio_slot.path:
        try:
            duration_s = probe_audio(Path(audio_slot.path)).duration_s
        except (OSError, ValueError):
            duration_s = None
    h3_reference_ready = bool(
        duration_s is not None and 2.0 <= duration_s <= 15.0
    )

    asset_id: str | None = None
    if bool(args.get("save_to_library", True)):
        asset = runtime.get_pipeline("tts").save_to_library(
            terminal,
            name=name_value,
            notes=" ".join(text.split())[:400],
            project_id=project_id,
        )
        asset_id = asset.id

    actions.append(f"generate_tts_audio:{asset_id or terminal.id}")
    warnings = list((terminal.params or {}).get("warnings") or [])
    if result_payloads is not None:
        result_payloads.append(
            {
                "ok": True,
                "job_id": terminal.id,
                "asset_id": asset_id,
                "style": style,
                "text": text,
                "used_respell": (terminal.params or {}).get("used_respell") or "",
                "duration_s": duration_s,
                "h3_reference_ready": h3_reference_ready,
                "audio_url": audio_slot.url,
                "audio_path": audio_slot.path,
                "padded_audio_url": padded_slot.url if padded_slot else None,
                "warnings": warnings,
            }
        )

    detail = f" ({duration_s:.1f}s)" if duration_s is not None else ""
    saved_note = f" and saved Voice asset {asset_id}" if asset_id else ""
    notes.append(
        f"Generated {style} speech{detail}, job {terminal.id}{saved_note}. "
        f"Audio: {audio_slot.url}"
        + (
            f" · padded H3 reference: {padded_slot.url}"
            if padded_slot and padded_slot.url
            else ""
        )
        + (
            " · within the 2–15s H3 voice-reference window."
            if h3_reference_ready
            else " · note: outside the 2–15s H3 voice-reference window."
        )
        + (f" Warnings: {'; '.join(warnings)}" if warnings else "")
    )


async def _handle_overlay(
    *,
    args: dict[str, Any],
    project_id: str,
    runtime: Any,
    actions: list[str],
    notes: list[str],
    result_payloads: list[dict[str, Any]] | None,
) -> None:
    title = str(args.get("title") or "").strip()
    author = str(args.get("author") or "").strip()
    if not title or not author:
        raise ValueError("overlay_poem_subtitles requires title and author")
    raw_lines = args.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError(
            "overlay_poem_subtitles requires ordered lines of {text, start_s}"
        )
    lines: list[dict[str, Any]] = []
    for item in raw_lines:
        if not isinstance(item, dict):
            raise TypeError("each poem line must be an object with text and start_s")
        line_text = str(item.get("text") or "").strip()
        if not line_text:
            raise ValueError("each poem line requires non-empty text")
        lines.append(
            {
                "text": line_text,
                "start_s": _optional_float(item.get("start_s"), default=0.0),
            }
        )

    source_path, source_label = _resolve_overlay_source(
        args=args,
        project_id=project_id,
        runtime=runtime,
    )
    try:
        data = Path(source_path).read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read the source video: {source_path}") from exc
    if not data:
        raise ValueError("the source video is empty")

    output_name = str(args.get("output_name") or "").strip() or f"poem_{title}"
    params: dict[str, Any] = {
        "title": title,
        "author": author,
        "dynasty": str(args.get("dynasty") or "唐").strip() or "唐",
        "seal": str(args.get("seal") or "狸").strip() or "狸",
        "lines": lines,
        "output_name": output_name,
        "project_id": project_id,
    }
    for key in ("width", "height"):
        if args.get(key) is not None:
            params[key] = int(args[key])

    job = runtime.create_job(
        pipeline_id="poem_overlay",
        asset_kind="productions",
        name=f"poem overlay: {title}",
        notes=f"{author} · {len(lines)} line(s)",
        params=params,
        project_id=project_id,
    )
    await runtime.start_pipeline_job(
        job,
        images={"video": (Path(source_path).name, data)},
    )
    terminal = await runtime.await_pipeline_job(job.id)
    if terminal is None:
        raise ValueError(f"Poem overlay job disappeared: {job.id}")
    if terminal.status != JobStatus.succeeded:
        raise ValueError(
            str(terminal.error or f"Poem overlay job status is {terminal.status.value}")
        )

    video_slot = terminal.outputs.get("video")
    if video_slot is None or not (video_slot.url or video_slot.path):
        raise ValueError("Poem overlay job completed without a video output")

    actions.append(f"overlay_poem_subtitles:{terminal.id}")
    overlay_meta = (terminal.params or {}).get("overlay") or {}
    if result_payloads is not None:
        result_payloads.append(
            {
                "ok": True,
                "job_id": terminal.id,
                "title": title,
                "author": author,
                "line_count": len(lines),
                "video_url": video_slot.url,
                "video_path": video_slot.path,
                "overlay": overlay_meta,
            }
        )
    notes.append(
        f"Rendered vertical poem subtitles for 《{title}》 onto {source_label} "
        f"({len(lines)} lines) → {video_slot.url}"
    )


def _resolve_overlay_source(
    *,
    args: dict[str, Any],
    project_id: str,
    runtime: Any,
) -> tuple[str, str]:
    source_shot_id = str(args.get("source_shot_id") or "").strip()
    source_job_id = str(args.get("source_job_id") or "").strip()
    output_kind = str(args.get("output_kind") or "").strip() or None
    if output_kind not in (None, "enhanced", "raw"):
        raise ValueError("output_kind must be enhanced or raw")
    if not source_shot_id and not source_job_id:
        raise ValueError(
            "overlay_poem_subtitles requires source_shot_id or source_job_id"
        )

    if source_shot_id:
        source_version = str(args.get("source_version") or "").strip() or None
        if source_version or source_job_id:
            try:
                resolved = resolve_source_clip(
                    project_id=project_id,
                    source_shot_id=source_shot_id,
                    source_version=source_version,
                    source_job_id=source_job_id or None,
                    output_kind=output_kind,  # type: ignore[arg-type]
                )
            except ClipGenerationError:
                resolved = resolve_latest_succeeded_clip(
                    project_id=project_id,
                    source_shot_id=source_shot_id,
                    output_kind=output_kind,  # type: ignore[arg-type]
                )
        else:
            resolved = resolve_latest_succeeded_clip(
                project_id=project_id,
                source_shot_id=source_shot_id,
                output_kind=output_kind,  # type: ignore[arg-type]
            )
        return str(resolved.path), f"shot {source_shot_id} ({resolved.source_filename})"

    job = _load_project_job(runtime, source_job_id, project_id)
    if job is None:
        raise ValueError(f"source job not found in this project: {source_job_id}")
    if job.status != JobStatus.succeeded:
        raise ValueError(
            f"source job {source_job_id} is {job.status.value}, not succeeded"
        )
    key = "video" if "video" in job.outputs else "video_raw"
    slot = job.outputs.get(key)
    if slot is None or not slot.path:
        raise ValueError(f"source job {source_job_id} has no materialized video output")
    return slot.path, f"job {source_job_id}"


def _load_project_job(
    runtime: Any, job_id: str, project_id: str
) -> JobRecord | None:
    job = runtime.load_job(job_id)
    if job is None:
        return None
    if (job.project_id or None) != project_id:
        return None
    return job


def _optional_float(value: Any, *, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise TypeError(f"expected a number, got {value!r}") from None


def workflow_default(key: str) -> str:
    return {
        "age": tts_workflow.DEFAULT_AGE,
        "rhyme": tts_workflow.DEFAULT_RHYME,
        "emotion": tts_workflow.DEFAULT_EMOTION,
    }[key]
