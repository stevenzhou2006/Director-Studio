from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.prompting import append_global_prompt, effective_global_prompt
from ...core.schemas import ComfyImageRef, JobRecord
from ..base import Pipeline
from . import panel_align, workflow


class ActorPipeline(Pipeline):
    id = "actor"
    asset_kind = "actors"
    display_name = "Actor Casting"
    description = (
        "Actor reference → master + multipanel three-view (workbench); optional wardrobe; bust crop."
    )

    @property
    def output_labels(self) -> dict[str, str]:
        return dict(workflow.OUTPUT_LABELS)

    def meta_defaults(self) -> dict[str, Any]:
        base = super().meta_defaults()
        base.update(
            {
                "routing": {
                    "actor_ref": {
                        "none": "Text-to-actor (description only)",
                        "any": "Reference image → master + three-view (workbench)",
                    },
                    "wardrobe_ref": {
                        "none": "Keep outfit from master / description",
                        "upload": "Extract clothing and transfer onto master",
                    },
                    "order": (
                        "master (actor ref + description) → multipanel three-view "
                        "(master + actor ref) → bust crop"
                    ),
                },
                "default_negative": workflow.DEFAULT_NEGATIVE,
                "default_description": workflow.DEFAULT_DESCRIPTION,
                "default_body_description": "",
                "default_hair_description": "",
                "fields": [
                    {"id": "description", "label": "Actor description", "required": True},
                    {
                        "id": "actor_image",
                        "label": "Actor reference (optional)",
                        "required": False,
                    },
                    {
                        "id": "wardrobe_image",
                        "label": "Wardrobe / model photo (optional)",
                        "required": False,
                    },
                ],
                "output_slots": [
                    {"key": "master", "label": workflow.OUTPUT_LABELS["master"]},
                    {
                        "key": "fullbody_threeview",
                        "label": workflow.OUTPUT_LABELS["fullbody_threeview"],
                    },
                    {
                        "key": "bust_threeview",
                        "label": workflow.OUTPUT_LABELS["bust_threeview"],
                    },
                    {
                        "key": "asset_sheet",
                        "label": workflow.OUTPUT_LABELS["asset_sheet"],
                    },
                    {
                        "key": "wardrobe_ref",
                        "label": workflow.OUTPUT_LABELS["wardrobe_ref"],
                        "conditional": True,
                    },
                ],
            }
        )
        return base

    def default_inputs(self) -> dict[str, tuple[str, bytes]]:
        """Upload a valid 1×1 blank for optional actor/wardrobe LoadImage slots."""
        return {workflow.BLANK_INPUT_KEY: workflow.blank_placeholder()}

    def build_prompt(
        self,
        job: JobRecord,
        *,
        uploaded_images: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        p = job.params
        description = (p.get("description") or "").strip()
        if not description and "actor" not in uploaded_images:
            raise ValueError("description is required when no actor reference is uploaded")

        description = append_global_prompt(
            description, effective_global_prompt(job.project_id)
        )
        return workflow.build_actor_prompt(
            description=description or workflow.DEFAULT_DESCRIPTION,
            body_description=p.get("body_description") or "",
            hair_description=p.get("hair_description") or "",
            negative_prompt=p.get("negative_prompt") or "",
            actor_image_name=uploaded_images.get("actor"),
            wardrobe_image_name=uploaded_images.get("wardrobe"),
            blank_image_name=uploaded_images.get(workflow.BLANK_INPUT_KEY),
            include_headwear=bool(p.get("include_headwear")),
            include_footwear=bool(p.get("include_footwear")),
            include_wardrobe=bool(p.get("include_wardrobe", True)),
            species=p.get("species") or workflow.SPECIES_AUTO,
            seed=job.seed,
            job_id=job.id,
        )

    def map_history_outputs(
        self,
        history: dict[str, Any],
        *,
        job: JobRecord | None = None,
    ) -> dict[str, ComfyImageRef]:
        mapped = workflow.map_history_outputs(history)
        if job is not None and not bool(
            (job.params or {}).get("include_wardrobe", True)
        ):
            # No wardrobe requested ⇒ the graph still saves a 1×1 blank; drop it.
            mapped.pop("wardrobe_ref", None)
        return mapped

    def library_input_keys(self) -> list[str]:
        return ["actor", "wardrobe"]

    def postprocess_job_outputs(self, job: JobRecord, saved: dict[str, Any]) -> None:
        """Align a quadruped turnaround so every view shares height and baseline."""
        species, _ = workflow.resolve_actor_identity(job.params or {})
        if species != workflow.SPECIES_QUADRUPED:
            return
        fullbody = saved.get("fullbody_threeview")
        bust = saved.get("bust_threeview")
        asset = saved.get("asset_sheet")
        if not (fullbody and bust and asset):
            return
        panel_align.normalize_turnaround(
            Path(fullbody), Path(bust), Path(asset)
        )

    def library_meta(self, job: JobRecord) -> dict[str, Any]:
        species, description = workflow.resolve_actor_identity(job.params or {})
        return {
            **(job.params or {}),
            "species": species,
            "description": description,
        }
