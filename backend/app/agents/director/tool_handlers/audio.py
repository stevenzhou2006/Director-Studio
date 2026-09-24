"""Speech (TTS) and poem-subtitle overlay tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ....core.library.audio import probe_audio
from ....core.library.store import load_asset
from ....core.media.clip_generations import (
    ClipGenerationError,
    resolve_latest_succeeded_clip,
    resolve_source_clip,
)
from ....core.projects.models import Shot, ShotVoiceRef
from ....core.projects.store import list_shots, save_shot
from ....core.schemas import JobRecord, JobStatus, LibraryAsset
from ....pipelines.tts import workflow as tts_workflow
from ..intent import resolve_shot

_TTS_TOOL_NAMES = frozenset({"generate_tts_audio", "generate_speech", "tts"})
_OVERLAY_TOOL_NAMES = frozenset(
    {"overlay_poem_subtitles", "poem_overlay", "overlay_poem"}
)
_POEM_META_TOOL_NAMES = frozenset({"set_poem", "set_poem_metadata"})


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
    if name in _POEM_META_TOOL_NAMES:
        await _handle_set_poem(
            args=args,
            project_id=project_id,
            actions=actions,
            notes=notes,
            result_payloads=result_payloads,
        )
        return True
    return False


async def _handle_set_poem(
    *,
    args: dict[str, Any],
    project_id: str,
    actions: list[str],
    notes: list[str],
    result_payloads: list[dict[str, Any]] | None,
) -> None:
    """Record the poem on a Shot so the titled frame + synced subtitles work."""
    from ..poem_meta import set_poem

    shot = _resolve_target_shot(args, project_id)
    if shot is None:
        raise ValueError(
            "set_poem requires a shot_id, shot_index, or title that matches a shot"
        )
    title = str(args.get("title") or "").strip()
    author = str(args.get("author") or "").strip()
    if not title or not author:
        raise ValueError("set_poem requires title and author")
    raw_lines = args.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError("set_poem requires ordered lines")

    updated = set_poem(
        shot,
        {
            "title": title,
            "author": author,
            "dynasty": str(args.get("dynasty") or "唐"),
            "seal": str(args.get("seal") or "狸"),
            "lines": raw_lines,
        },
    )
    save_shot(updated)
    poem = updated.meta["poem"]
    actions.append(f"set_poem:{shot.id}")
    if result_payloads is not None:
        result_payloads.append(
            {
                "ok": True,
                "shot_id": shot.id,
                "title": poem["title"],
                "author": poem["author"],
                "dynasty": poem["dynasty"],
                "line_count": len(poem["lines"]),
            }
        )
    notes.append(
        f"Recorded poem 《{poem['title']}》 · {poem['dynasty']}·{poem['author']} "
        f"({len(poem['lines'])} line(s)) on {shot.id}. Regenerate the Layout "
        f"(queue_ref_frame) to produce the font-composited titled preview."
    )


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

    # Guard: never burn a throwaway take when the target Shot already carries an
    # H3-ready voice. No Shot named, or only non-ready voices attached -> let the
    # Director decide from the prompt and generate normally.
    target_shot = _resolve_target_shot(args, project_id)
    if target_shot is not None and not bool(args.get("force", False)):
        ready = _h3_ready_voice_names(target_shot)
        if ready:
            actions.append(f"generate_tts_audio:skipped:{target_shot.id}")
            if result_payloads is not None:
                result_payloads.append(
                    {
                        "ok": True,
                        "skipped": True,
                        "shot_id": target_shot.id,
                        "reason": "shot already has an H3-ready voice",
                        "voices": ready,
                    }
                )
            notes.append(
                f"Skipped generate_tts_audio: Shot {target_shot.id} already has "
                f"H3-ready voice(s): {', '.join(ready)}. Not generating a "
                f"duplicate take. Pass force=true only if the user explicitly "
                f"wants another."
            )
            return

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
        bound = _bind_voice_to_shot(
            asset=asset,
            args=args,
            project_id=project_id,
            speaker=str(params.get("speaker") or "").strip(),
        )
        if bound is not None:
            notes.append(bound)

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


def _resolve_target_shot(args: dict[str, Any], project_id: str) -> Shot | None:
    """Resolve the Shot the director named via shot_id/shot_index/title."""
    shot_id = str(args.get("shot_id") or "").strip()
    shot_index = args.get("shot_index") or args.get("index")
    title = str(args.get("title") or "").strip()
    if not (shot_id or shot_index or title):
        return None
    return resolve_shot(
        list_shots(project_id),
        shot_id=shot_id or None,
        shot_index=shot_index,
        title=title or None,
    )


def _h3_ready_voice_names(shot: Shot) -> list[str]:
    """Names of voices already bound to this Shot that are H3-ready."""
    names: list[str] = []
    for ref in shot.voice_refs:
        asset = load_asset("voices", ref.asset_id)
        if asset is not None and bool((asset.meta or {}).get("h3_ready")):
            names.append(asset.name or ref.asset_id)
    return names


def _bind_voice_to_shot(
    *,
    asset: LibraryAsset,
    args: dict[str, Any],
    project_id: str,
    speaker: str,
) -> str | None:
    """Attach a freshly saved Voice to the Shot the director named, if any."""
    shot = _resolve_target_shot(args, project_id)
    if shot is None:
        if not (
            args.get("shot_id")
            or args.get("shot_index")
            or args.get("index")
            or args.get("title")
        ):
            return None
        return (
            f"Voice {asset.id} saved but NOT bound: no Shot matched the given "
            f"shot_id/index/title."
        )
    meta = asset.meta or {}
    if not bool(meta.get("h3_ready")):
        return (
            f"Voice {asset.id} NOT bound to {shot.id}: outside the 2–15s H3 "
            f"reference window (duration={meta.get('duration_s')})."
        )
    if any(ref.asset_id == asset.id for ref in shot.voice_refs):
        return f"Voice {asset.id} already bound to {shot.id}."
    used_indices = {ref.audio_index for ref in shot.voice_refs}
    audio_index = next((i for i in (1, 2, 3) if i not in used_indices), None)
    if audio_index is None:
        return f"Voice {asset.id} NOT bound: {shot.id} already has 3 voice refs."
    file_key = str(meta.get("h3_file_key") or "audio")
    if not (asset.files or {}).get(file_key):
        file_key = next(iter(asset.files or {}), "audio")
    ref = ShotVoiceRef(
        asset_id=asset.id,
        audio_index=audio_index,
        file_key=file_key,
        speaker=speaker,
        notes="director TTS auto-bind",
    )
    updated = shot.model_copy(update={"voice_refs": [*shot.voice_refs, ref]})
    meta_out = dict(updated.meta or {})
    meta_out["prompt_voice_signature"] = ""
    updated = updated.model_copy(update={"meta": meta_out})
    save_shot(updated)
    return (
        f"Bound Voice {asset.id} to {shot.id} as audio_{audio_index} "
        f"(file_key={file_key}); H3 will recite with this accent."
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
    from ..poem_meta import get_poem, set_poem

    source_shot = _resolve_overlay_shot(args=args, project_id=project_id)
    poem = get_poem(source_shot) if source_shot is not None else {}

    title = str(args.get("title") or poem.get("title") or "").strip()
    author = str(args.get("author") or poem.get("author") or "").strip()
    if not title or not author:
        raise ValueError(
            "overlay_poem_subtitles requires title and author (or a shot with "
            "poem metadata)"
        )
    dynasty = str(args.get("dynasty") or poem.get("dynasty") or "唐").strip() or "唐"
    seal = str(args.get("seal") or poem.get("seal") or "狸").strip() or "狸"

    raw_lines = args.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raw_lines = poem.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError(
            "overlay_poem_subtitles requires ordered lines of {text[, start_s]}"
        )
    lines: list[dict[str, Any]] = []
    needs_timing = False
    for item in raw_lines:
        if isinstance(item, dict):
            line_text = str(item.get("text") or "").strip()
            start_raw = item.get("start_s")
        elif isinstance(item, str):
            line_text = item.strip()
            start_raw = None
        else:
            raise TypeError("each poem line must be a string or {text, start_s}")
        if not line_text:
            raise ValueError("each poem line requires non-empty text")
        if start_raw is None:
            needs_timing = True
            lines.append({"text": line_text, "start_s": None})
        else:
            lines.append(
                {"text": line_text, "start_s": _optional_float(start_raw, default=0.0)}
            )

    if needs_timing:
        if source_shot is None:
            raise ValueError(
                "auto line timing requires source_shot_id with bound recitation audio"
            )
        from ....pipelines.poem_overlay.timing import (
            PoemTimingError,
            derive_line_starts,
        )

        try:
            starts = derive_line_starts([e["text"] for e in lines], shot=source_shot)
        except PoemTimingError as exc:
            raise ValueError(f"could not auto-time poem lines: {exc}") from exc
        for entry, start in zip(lines, starts):
            if entry.get("start_s") is None:
                entry["start_s"] = start
    for entry in lines:
        entry["start_s"] = float(entry.get("start_s") or 0.0)

    # Persist the resolved poem so the layout-frame titled preview and later
    # overlays reuse the same title/attribution without re-supplying it.
    if source_shot is not None:
        save_shot(
            set_poem(
                source_shot,
                {
                    "title": title,
                    "author": author,
                    "dynasty": dynasty,
                    "seal": seal,
                    "lines": lines,
                },
            )
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
        "dynasty": dynasty,
        "seal": seal,
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


def _resolve_overlay_shot(
    *, args: dict[str, Any], project_id: str
) -> Shot | None:
    """Best-effort resolve the shot the overlay targets (for poem defaults/timing)."""
    source_shot_id = str(args.get("source_shot_id") or "").strip()
    if not source_shot_id:
        return None
    return resolve_shot(list_shots(project_id), shot_id=source_shot_id)


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
