from __future__ import annotations

from typing import Any

from ...core.prompting import (
    append_global_prompt,
    append_scene_style_authority,
    append_style_contradiction_override,
    append_style_lock,
    effective_global_negative,
    effective_global_prompt,
    effective_style_lock,
)
from ...core.schemas import ComfyImageRef, JobRecord, LibraryAsset
from ..base import Pipeline
from . import workflow


def _pack_has_scene(params: dict[str, Any]) -> bool:
    """True when the reference pack contains a scene library asset."""
    source_ids = params.get("source_asset_ids") or []
    if isinstance(source_ids, list) and any(
        str(x).startswith("scn_") for x in source_ids
    ):
        return True
    ref_labels = params.get("ref_labels") or []
    if isinstance(ref_labels, list):
        for label in ref_labels:
            if "scene" in str(label).lower().split():
                return True
    return False


class RefFramePipeline(Pipeline):
    id = "ref_frame"
    asset_kind = "layouts"
    display_name = "Layout Reference Frame"
    description = (
        "Compose a layout reference-frame still from a blocking description and ordered "
        "reference images (actor/scene/etc.). Saved to library layouts with "
        "review_status=pending_review."
    )
    enabled = True

    def __init__(self) -> None:
        # Only enable when the checked-in workflow shell validates
        self.enabled = workflow.workflow_file_valid()

    @property
    def output_labels(self) -> dict[str, str]:
        return dict(workflow.OUTPUT_LABELS)

    def meta_defaults(self) -> dict[str, Any]:
        base = super().meta_defaults()
        base.update(
            {
                "defaults": {
                    "max_ref_images": workflow.MAX_REF_IMAGES,
                },
                "fields": [
                    {
                        "id": "description",
                        "label": "Layout description (blocking)",
                        "required": True,
                    },
                    {
                        "id": "image_keys",
                        "label": "Ordered logical input keys (ref_0…ref_n)",
                        "required": False,
                    },
                    {
                        "id": "shot_id",
                        "label": "Source shot id (optional)",
                        "required": False,
                    },
                    {
                        "id": "source_asset_ids",
                        "label": "Source library asset ids",
                        "required": False,
                    },
                ],
                "output_slots": [
                    {"key": "layout", "label": workflow.OUTPUT_LABELS["layout"]},
                    {
                        "key": "layout_titled",
                        "label": workflow.OUTPUT_LABELS["layout_titled"],
                    },
                ],
                "node_ids": {
                    "description": workflow.NODE_DESCRIPTION,
                    "sampler": workflow.NODE_SAMPLER,
                    "save": workflow.NODE_SAVE,
                    "ref_image_0": workflow.NODE_REF_IMAGE_1,
                },
            }
        )
        return base

    def build_prompt(
        self,
        job: JobRecord,
        *,
        uploaded_images: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        p = job.params or {}
        description = (p.get("description") or "").strip()
        if not description:
            raise ValueError("description is required")
        # When the shot carries a poem, the title/attribution are composited in
        # post with real fonts. The model must NOT render any CJK text or seals
        # (it garbles them), so reserve the margin as clean blank rice paper.
        poem = p.get("poem")
        if isinstance(poem, dict) and str(poem.get("title") or "").strip():
            description = (
                description
                + "\n\nTITLE/ATTRIBUTION HANDLING: Do NOT render any Chinese "
                "characters, poem title, author/dynasty attribution, seal, or any "
                "on-screen text anywhere in the frame. Leave the right vertical "
                "margin as clean, empty rice-paper negative space reserved for a "
                "post-composited title card. The frame itself must contain no text."
            )
        description = append_global_prompt(
            description, effective_global_prompt(job.project_id)
        )
        # Style policy: an explicit user-requested lock wins; otherwise the
        # imported scene asset is the style authority, so a Layout can never
        # drift into an art style nobody asked for.
        style_lock = effective_style_lock(job.project_id)
        if style_lock:
            description = append_style_lock(description, style_lock)
            # Final backstop: a stale medium word in the prompt body would
            # otherwise fight the lock.
            description = append_style_contradiction_override(description, style_lock)
        elif _pack_has_scene(p):
            description = append_scene_style_authority(description)

        image_keys = p.get("image_keys")
        if isinstance(image_keys, list) and image_keys:
            ordered_keys = [str(k) for k in image_keys]
        else:
            # Prefer ref_0, ref_1, … then any remaining uploads in stable order
            ref_keys = sorted(
                (k for k in uploaded_images if k.startswith("ref_")),
                key=lambda k: (
                    int(k.split("_", 1)[1])
                    if k.split("_", 1)[-1].isdigit()
                    else 10**9,
                    k,
                ),
            )
            other = [k for k in uploaded_images if k not in ref_keys]
            ordered_keys = ref_keys + other

        image_names: list[str] = []
        for key in ordered_keys:
            name = uploaded_images.get(key)
            if name:
                image_names.append(name)

        if not image_names and uploaded_images:
            image_names = list(uploaded_images.values())

        output_prefix = p.get("output_prefix")
        ref_labels = p.get("ref_labels")
        if not isinstance(ref_labels, list):
            ref_labels = []
        return workflow.build_layout_prompt(
            description=description,
            image_names=image_names,
            seed=job.seed,
            output_prefix=output_prefix,
            job_id=job.id,
            ref_labels=[str(x) for x in ref_labels],
            aspect_ratio=str(p.get("aspect_ratio") or ""),
            negative_extra=effective_global_negative(job.project_id),
        )

    def map_history_outputs(
        self,
        history: dict[str, Any],
        *,
        job: JobRecord | None = None,
    ) -> dict[str, ComfyImageRef]:
        return workflow.map_history_outputs(history)

    def postprocess_job_outputs(
        self, job: JobRecord, saved: dict[str, Any]
    ) -> None:
        """Composite a font-correct titled preview when the shot carries a poem.

        The model-rendered ``layout`` stays text-free (it is the H3 reference);
        ``layout_titled`` is a separate preview with the title card burned in by
        real fonts, so the attribution is always correct.
        """
        params = job.params or {}
        poem = params.get("poem")
        if not isinstance(poem, dict):
            return
        title = str(poem.get("title") or "").strip()
        author = str(poem.get("author") or "").strip()
        if not title or not author:
            return
        source = saved.get("layout")
        if not source:
            return
        from pathlib import Path

        from ..poem_overlay.overlay import PoemOverlayError, render_poem_title_still

        source_path = Path(source)
        titled_path = source_path.with_name("layout_titled.png")
        raw_lines = poem.get("lines")
        columns: list[str] = []
        if isinstance(raw_lines, list):
            for item in raw_lines:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                else:
                    text = str(item or "").strip()
                if text:
                    columns.append(text)
        try:
            render_poem_title_still(
                input_path=source_path,
                output_path=titled_path,
                title=title,
                author=author,
                dynasty=str(poem.get("dynasty") or "唐"),
                seal_text=str(poem.get("seal") or "狸"),
                columns=columns,
            )
        except (PoemOverlayError, OSError) as exc:
            params["warnings"] = list(params.get("warnings") or []) + [
                f"titled preview skipped: {exc}"
            ]
            return
        saved["layout_titled"] = titled_path

    def library_input_keys(self) -> list[str]:
        return []

    def save_to_library(
        self,
        job: JobRecord,
        *,
        name: str | None = None,
        notes: str | None = None,
        project_id: str | None = None,
    ) -> LibraryAsset:
        from ...core.library import save_asset_from_job

        p = job.params or {}
        source_refs = p.get("source_asset_ids") or []
        if not isinstance(source_refs, list):
            source_refs = []
        # Prefer explicit, then job, then params.project_id (shot pipeline)
        resolved = project_id or job.project_id or p.get("project_id")

        # Only the text-free ``layout`` is persisted to the library: it is the
        # H3 reference. The font-composited ``layout_titled`` preview stays a
        # job output and must never condition H3 (which would morph the text).
        return save_asset_from_job(
            job,
            name=name,
            notes=notes,
            file_keys=["layout"],
            input_keys=self.library_input_keys(),
            meta={
                "review_status": "pending_review",
                "source_shot_id": p.get("shot_id"),
                "source_refs": list(source_refs),
            },
            project_id=resolved if isinstance(resolved, str) else project_id,
        )
