"""Project-level continuity anchor for cross-shot character and location persistence.

The Director plans every shot independently, which lets the same character or the
same room drift between shots (a different actor view, a different scene asset, a
different wardrobe). This module records the first authoritative binding per
character and per location and lets casting reuse it deterministically so every
shot conditions H3 on the *same* identity and the *same* location asset.

The anchor is a reuse aid, not a hard creative lock: it is applied when shots are
planned, re-planned, or recast, and it never invents assets. A missing or deleted
anchor asset is skipped rather than forced.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .models import RefRole, Shot

CONTINUITY_FILENAME = "continuity.json"

_ACTOR_ROLES = (RefRole.actor,)
_SCENE_ROLES = (RefRole.scene,)
_PROP_ROLES = (RefRole.prop,)


def _normalize_key(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", (name or "").lower())
    return cleaned.strip()


class CastAnchor(BaseModel):
    character_key: str
    asset_id: str
    file_key: str = ""
    display_name: str = ""


class LocationAnchor(BaseModel):
    scene_id: str
    scene_key: str
    asset_id: str
    display_name: str = ""


class PropAnchor(BaseModel):
    prop_key: str
    asset_id: str
    file_key: str = ""
    display_name: str = ""


class ProjectContinuity(BaseModel):
    project_id: str
    cast: list[CastAnchor] = Field(default_factory=list)
    locations: list[LocationAnchor] = Field(default_factory=list)
    props: list[PropAnchor] = Field(default_factory=list)
    updated_at: str = ""

    def cast_by_key(self) -> dict[str, CastAnchor]:
        return {anchor.character_key: anchor for anchor in self.cast}

    def location_by_key(self) -> dict[str, LocationAnchor]:
        return {anchor.scene_key: anchor for anchor in self.locations}

    def props_by_key(self) -> dict[str, PropAnchor]:
        return {anchor.prop_key: anchor for anchor in self.props}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def continuity_path(project_id: str) -> Path:
    from ...config import settings
    from ..paths import ensure_project_tree

    ensure_project_tree(project_id)
    return settings.projects_dir / project_id / "agent" / CONTINUITY_FILENAME


def load_continuity(project_id: str) -> ProjectContinuity | None:
    path = continuity_path(project_id)
    if not path.exists():
        return None
    try:
        return ProjectContinuity.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        return None


def save_continuity(project_id: str, continuity: ProjectContinuity) -> Path:
    path = continuity_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = continuity.model_copy(update={"project_id": project_id, "updated_at": _now()})
    temp = path.with_suffix(".json.tmp")
    temp.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(path)
    return path


def derive_continuity(
    project_id: str,
    shots: list[Shot],
    index: dict[str, object],
) -> ProjectContinuity:
    """Record the first authoritative actor/scene/prop binding seen across ``shots``."""
    cast: dict[str, CastAnchor] = {}
    locations: dict[str, LocationAnchor] = {}
    props: dict[str, PropAnchor] = {}
    for shot in shots:
        for ref in shot.refs or []:
            asset = index.get(ref.asset_id)
            name = str(getattr(asset, "name", "") or "")
            if ref.role in _ACTOR_ROLES:
                key = _normalize_key(name) or ref.asset_id
                if key and key not in cast:
                    cast[key] = CastAnchor(
                        character_key=key,
                        asset_id=ref.asset_id,
                        file_key=ref.file_key or "",
                        display_name=name,
                    )
            elif ref.role in _SCENE_ROLES:
                scene_key = _normalize_key(shot.scene_id) or ref.asset_id
                if scene_key and scene_key not in locations:
                    locations[scene_key] = LocationAnchor(
                        scene_id=shot.scene_id,
                        scene_key=scene_key,
                        asset_id=ref.asset_id,
                        display_name=name,
                    )
            elif ref.role in _PROP_ROLES:
                key = _normalize_key(name) or ref.asset_id
                if key and key not in props:
                    props[key] = PropAnchor(
                        prop_key=key,
                        asset_id=ref.asset_id,
                        file_key=ref.file_key or "",
                        display_name=name,
                    )
    return ProjectContinuity(
        project_id=project_id,
        cast=list(cast.values()),
        locations=list(locations.values()),
        props=list(props.values()),
        updated_at=_now(),
    )


def apply_continuity_to_shot(
    shot: Shot,
    continuity: ProjectContinuity | None,
    index: dict[str, object],
) -> tuple[Shot, list[str]]:
    """Force a shot's actor/scene/prop refs onto the anchored assets.

    Returns the updated shot and a list of human-readable notes describing each
    applied correction. The shot is returned unchanged when there is no anchor or
    when an anchor asset is no longer available.
    """
    if continuity is None or not shot.refs:
        return shot, []

    cast = continuity.cast_by_key()
    locations = continuity.location_by_key()
    props = continuity.props_by_key()
    notes: list[str] = []
    used_bindings: set[tuple[str, str]] = {
        (ref.role.value, ref.asset_id) for ref in shot.refs
    }
    new_refs = []
    for ref in shot.refs:
        updated = ref
        if ref.role in _ACTOR_ROLES:
            asset = index.get(ref.asset_id)
            key = _normalize_key(str(getattr(asset, "name", "") or "")) or ref.asset_id
            anchor = cast.get(key)
            if (
                anchor is not None
                and anchor.asset_id in index
                and anchor.asset_id != ref.asset_id
                and (ref.role.value, anchor.asset_id) not in used_bindings
            ):
                updated = updated.model_copy(update={"asset_id": anchor.asset_id})
                used_bindings.add((ref.role.value, anchor.asset_id))
                notes.append(
                    f"cast '{anchor.display_name or key}' pinned to {anchor.asset_id}"
                )
            anchor = cast.get(key)
            if (
                anchor is not None
                and anchor.file_key
                and anchor.asset_id == updated.asset_id
                and (index.get(updated.asset_id) is not None)
                and (updated.file_key or "") != anchor.file_key
            ):
                asset_files = getattr(index.get(updated.asset_id), "files", {}) or {}
                if asset_files.get(anchor.file_key):
                    updated = updated.model_copy(update={"file_key": anchor.file_key})
                    notes.append(
                        f"actor view pinned to {anchor.file_key}"
                    )
        elif ref.role in _SCENE_ROLES:
            scene_key = _normalize_key(shot.scene_id)
            anchor = locations.get(scene_key)
            if (
                anchor is not None
                and anchor.asset_id in index
                and anchor.asset_id != ref.asset_id
                and (ref.role.value, anchor.asset_id) not in used_bindings
            ):
                updated = updated.model_copy(update={"asset_id": anchor.asset_id})
                used_bindings.add((ref.role.value, anchor.asset_id))
                notes.append(
                    f"location '{shot.scene_id}' pinned to {anchor.asset_id}"
                )
        elif ref.role in _PROP_ROLES:
            asset = index.get(ref.asset_id)
            key = _normalize_key(str(getattr(asset, "name", "") or "")) or ref.asset_id
            anchor = props.get(key)
            if (
                anchor is not None
                and anchor.asset_id in index
                and anchor.asset_id != ref.asset_id
                and (ref.role.value, anchor.asset_id) not in used_bindings
            ):
                updated = updated.model_copy(update={"asset_id": anchor.asset_id})
                used_bindings.add((ref.role.value, anchor.asset_id))
                notes.append(
                    f"prop '{anchor.display_name or key}' pinned to {anchor.asset_id}"
                )
            anchor = props.get(key)
            if (
                anchor is not None
                and anchor.file_key
                and anchor.asset_id == updated.asset_id
                and (index.get(updated.asset_id) is not None)
                and (updated.file_key or "") != anchor.file_key
            ):
                asset_files = getattr(index.get(updated.asset_id), "files", {}) or {}
                if asset_files.get(anchor.file_key):
                    updated = updated.model_copy(update={"file_key": anchor.file_key})
                    notes.append(f"prop view pinned to {anchor.file_key}")
        new_refs.append(updated)
    if not notes:
        return shot, []
    return shot.model_copy(update={"refs": new_refs}), notes


def continuity_hint(continuity: ProjectContinuity | None) -> str:
    """Compact locked-cast/location/prop block for the planner prompt."""
    if continuity is None or not (
        continuity.cast or continuity.locations or continuity.props
    ):
        return ""
    lines: list[str] = []
    if continuity.cast:
        lines.append("Locked cast (reuse these exact asset_id + file_key for this character):")
        for anchor in continuity.cast:
            lines.append(
                f"- {anchor.display_name or anchor.character_key}: "
                f"asset_id={anchor.asset_id} file_key={anchor.file_key or 'default'}"
            )
    if continuity.locations:
        lines.append("Locked locations (reuse this exact scene asset_id per scene_id):")
        for anchor in continuity.locations:
            lines.append(
                f"- scene_id={anchor.scene_id}: asset_id={anchor.asset_id}"
            )
    if continuity.props:
        lines.append(
            "Locked props/vehicles (reuse this exact asset_id + file_key "
            "for this object in every shot where it appears):"
        )
        for anchor in continuity.props:
            lines.append(
                f"- {anchor.display_name or anchor.prop_key}: "
                f"asset_id={anchor.asset_id} file_key={anchor.file_key or 'default'}"
            )
    return "\n".join(lines)
