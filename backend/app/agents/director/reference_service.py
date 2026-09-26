"""Reference-frame briefs and deterministic reference image selection."""

from __future__ import annotations

import logging
import re

from ...core.library.store import list_assets
from ...core.projects.layouts import LayoutBrief, LayoutReference, LayoutSourceRef
from ...core.projects.models import Project, RefRole, Shot
from ...core.schemas import LibraryAsset

logger = logging.getLogger("director_studio.director.reference")


_TAIL_FRAME_IMAGE1_NOTES = (
    "Preserve requested continuity as Image1. Apply only the user's stated changes. "
    "Do not recreate a contact sheet, introduce a new camera angle without instruction, "
    "or keep motion blur and compression artifacts as identity features."
)

# Multi-panel actor turnaround sheets. Always reduced to their front panel before
# being fed to Qwen Edit, which otherwise copies the panel structure.
_SHEET_FILE_KEYS = ("fullbody_threeview", "bust_threeview", "asset_sheet")


def build_tail_frame_revision_brief(
    layout: LayoutReference,
    additional_source_refs: list[LayoutSourceRef] | None = None,
    *,
    feedback: str = "",
) -> LayoutBrief:
    """Build a Qwen LayoutBrief that uses an extracted tail frame as Image1."""
    extras = list(additional_source_refs or [])
    if len(extras) > 2:
        raise ValueError(
            "a tail-frame redraw accepts at most 3 Qwen source images "
            "(the extracted Layout plus up to 2 additional sources)"
        )
    asset_id = (layout.asset_id or "").strip()
    if not asset_id:
        raise ValueError(
            f"LayoutReference has no generated image to revise: {layout.id}"
        )
    notes = _TAIL_FRAME_IMAGE1_NOTES
    cleaned = feedback.strip()
    if cleaned:
        notes = f"{notes} User feedback: {cleaned}"
    return LayoutBrief(
        purpose=layout.purpose,
        state_description=layout.state_description,
        time_hint=layout.time_hint,
        source_refs=[
            LayoutSourceRef(
                role=RefRole.layout_ref_frame,
                asset_id=asset_id,
                file_key="layout",
                notes=notes,
            ),
            *extras,
        ],
    )


def _match_library_scene(project: Project, shot: Shot) -> LibraryAsset | None:
    """Best-effort scene asset from library by scene_id / title / script tokens."""
    scenes = list_assets("scenes", project_id=project.id, include_unassigned=True)
    if not scenes:
        return None
    needles = [
        (shot.scene_id or "").lower(),
        (shot.title or "").lower(),
        (shot.script_beat or "").lower()[:80],
        (project.script_text or "").lower()[:200],
    ]
    best: LibraryAsset | None = None
    best_score = 0
    for asset in scenes:
        hay = f"{asset.name} {asset.notes} {asset.id}".lower()
        score = 0
        if (asset.project_id or None) == project.id:
            score += 1
        for n in needles:
            if n and n in hay:
                score += 2
            for word in n.replace("_", " ").split():
                if len(word) > 3 and word in hay:
                    score += 1
        if score > best_score:
            best_score = score
            best = asset
    # If no textual match, still return the only scene (single-location shows)
    if best is None and len(scenes) == 1:
        return scenes[0]
    if best is not None and best_score > 0:
        return best
    owned = [s for s in scenes if (s.project_id or None) == project.id]
    if len(owned) == 1:
        return owned[0]
    return scenes[0] if len(scenes) == 1 else None


def _match_library_actor(project: Project, shot: Shot) -> LibraryAsset | None:
    """Best-effort actor from project pool by name tokens in title/beat/script."""
    actors = list_assets("actors", project_id=project.id, include_unassigned=True)
    if not actors:
        return None
    hay = " ".join(
        [
            shot.title or "",
            shot.script_beat or "",
            " ".join(shot.dialogue or []),
            (project.script_text or "")[:400],
        ]
    ).lower()
    best: LibraryAsset | None = None
    best_score = 0
    for asset in actors:
        score = 1 if (asset.project_id or None) == project.id else 0
        name = (asset.name or "").lower()
        if name and name in hay:
            score += 5
        for word in name.replace("_", " ").split():
            if len(word) > 2 and word in hay:
                score += 2
        files = asset.files or {}
        if files.get("fullbody_threeview") or files.get("bust_threeview"):
            score += 1
        if score > best_score:
            best_score = score
            best = asset
    if best is not None and best_score > 0:
        return best
    owned = [a for a in actors if (a.project_id or None) == project.id]
    if len(owned) == 1:
        return owned[0]
    return actors[0] if len(actors) == 1 else None


def build_ref_frame_brief(
    project: Project,
    shot: Shot,
    *,
    ref_labels: list[str] | None = None,
) -> str:
    """
    Script + shot beat + dialogue brief for layout reference-frame generation.

    Must ground the still in story action while ref images carry identity/set.
    Explicitly forbids turnaround / three-view sheet layouts (common Qwen Edit pollution).
    """
    dialogue = shot.dialogue or []
    if isinstance(dialogue, str):
        dialogue = [dialogue] if dialogue else []
    dial_block = "\n".join(f'- "{d}"' for d in dialogue if d) or "- (no spoken lines)"

    # Keep script context short but real — full screenplay can drown the beat
    script = (project.script_text or "").strip()
    if len(script) > 1200:
        script = script[:1200] + "\n…"

    labels = ref_labels or []
    label_block = "\n".join(f"- {lab}" for lab in labels) or "- (no refs resolved)"

    return (
        "=== STORY / SCRIPT CONTEXT ===\n"
        f"{script}\n\n"
        "=== THIS SHOT ===\n"
        f"scene_id: {shot.scene_id}\n"
        f"title: {shot.title}\n"
        f"duration_s: {shot.duration_s}\n"
        f"blocking / action: {shot.script_beat}\n"
        f"dialogue:\n{dial_block}\n\n"
        "=== REFERENCE ROLES ===\n"
        f"{label_block}\n\n"
        "=== TASK ===\n"
        "Generate ONE photoreal production still for this shot (blocking board for video).\n"
        "HARD RULES:\n"
        "- One continuous frame, natural camera, clean photoreal materials (no oily mush).\n"
        "- Character stands physically in the set: feet on floor, correct scale vs door/bench.\n"
        "- Blocking action is primary (pacing, walking, stopping) — match script_beat.\n"
        "- Scene ref = architecture/lighting; Character ref = face/hair/outfit only.\n"
        "- FORBIDDEN: poster/sticker of person on frosted glass, reflection-only person, "
        "floating cutout, character sheet / three-view, studio void, melted wall texture, "
        "empty corridor with no person.\n"
        "- No comic panels, no watermark, no UI text."
    )


def _crop_sheet_front_panel(
    data: bytes,
    *,
    force: bool = False,
) -> tuple[str, bytes] | None:
    """If ref is a multi-panel sheet, take the left (front) panel only.

    Fullbody three-views are often ~1.5:1 (three near-square panels), not 3:1.
    """
    try:
        import io

        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        w, h = im.size
        if w < 64 or h < 64:
            return None
        # Horizontal 2–3 panel sheets (common three-view ~1.45–3.0 aspect)
        if force or w >= int(h * 1.35):
            panel = im.crop((0, 0, max(w // 3, 1), h))
        # Vertical stacked sheets (rare)
        elif h >= int(w * 1.35):
            panel = im.crop((0, 0, w, max(h // 3, 1)))
        else:
            return None
        buf = io.BytesIO()
        panel.save(buf, format="PNG")
        return "actor_front_panel.png", buf.getvalue()
    except Exception:
        logger.exception("crop sheet front panel failed")
        return None


def combine_actor_stills(
    stills: list[tuple[str, bytes]],
) -> tuple[str, bytes] | None:
    """Lay actor identity stills side by side into one reference image.

    Used when two actor references plus a scene and a prop would exceed the
    three-image Qwen limit. Packing the actors frees a slot so a real prop
    asset can still be attached instead of being invented by the model.
    """
    try:
        import io

        from PIL import Image
    except ImportError:
        return None
    try:
        opened = [
            Image.open(io.BytesIO(data)).convert("RGB") for _name, data in stills
        ]
        if len(opened) < 2:
            return None
        target_h = min(image.height for image in opened)
        resized = []
        for image in opened:
            scale = target_h / image.height
            resized.append(
                image.resize((max(1, int(image.width * scale)), target_h))
            )
        divider = max(4, target_h // 200)
        total_w = sum(image.width for image in resized) + divider * (len(resized) - 1)
        canvas = Image.new("RGB", (total_w, target_h), (255, 255, 255))
        x = 0
        for index, image in enumerate(resized):
            canvas.paste(image, (x, 0))
            x += image.width
            if index < len(resized) - 1:
                x += divider
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return "actor_pair.png", buf.getvalue()
    except Exception:
        logger.exception("combine actor stills failed")
        return None


_ANGLE_PLATE_RE = re.compile(r"_h(-?\d+)_v(m?\d+)")


def _parse_angle(raw: str) -> int:
    # ``vm30`` encodes -30 (vertical minus 30); plain digits are positive.
    if raw.startswith("m"):
        return -int(raw[1:])
    return int(raw)


def _azimuth_delta(a: int, b: int) -> int:
    return abs((a - b + 180) % 360 - 180)


def match_scene_angle_plate(asset: LibraryAsset, shot: Shot) -> str | None:
    """Pick the scene angle plate that matches the shot's camera intent.

    Scene assets carry multi-angle plates whose file keys encode the camera
    azimuth/elevation (``..._h<deg>_v<deg>``). When the shot explicitly names a
    camera direction, returning the matching plate keeps the Layout's background
    geography grounded instead of letting the model re-imagine the set from a
    mismatched master viewpoint. Returns ``None`` when the shot carries no
    explicit angle signal or no plate is close enough, so callers keep the
    existing neutral-plate priority.
    """
    files = dict(asset.files or {})
    plates: list[tuple[str, int, int]] = []
    for key in files:
        match = _ANGLE_PLATE_RE.search(str(key))
        if match and files.get(key):
            plates.append(
                (
                    str(key),
                    _parse_angle(match.group(1)),
                    _parse_angle(match.group(2)),
                )
            )
    if not plates:
        return None

    text = " ".join(
        part
        for part in (shot.title, shot.camera_angle, shot.camera_motion, shot.composition)
        if isinstance(part, str)
    ).lower()
    if not text.strip():
        return None

    desired_az: int | None = None
    if any(w in text for w in ("reverse", "back view", "from behind", "背面", "反打")):
        desired_az = 180
    elif any(w in text for w in ("front-left", "front left", "左前")):
        desired_az = 315
    elif any(w in text for w in ("front-right", "front right", "右前")):
        desired_az = 45
    elif any(w in text for w in ("left side", "from the left", "左侧")):
        desired_az = 270
    elif any(w in text for w in ("right side", "from the right", "右侧")):
        desired_az = 90
    elif any(w in text for w in ("front", "正面")):
        desired_az = 0

    desired_el: int | None = None
    if any(w in text for w in ("bird", "overhead", "aerial", "俯视", "俯瞰")):
        desired_el = 45
    elif any(w in text for w in ("low angle", "worm", "仰拍", "仰视")):
        desired_el = -30

    if desired_az is None and desired_el is None:
        return None

    def score(plate: tuple[str, int, int]) -> int:
        _key, az, el = plate
        total = 0
        if desired_az is not None:
            total += _azimuth_delta(az, desired_az)
        if desired_el is not None:
            total += 2 * abs(el - desired_el)
        return total

    best = min(plates, key=score)
    if desired_az is not None and _azimuth_delta(best[1], desired_az) > 45:
        return None
    if desired_el is not None and abs(best[2] - desired_el) > 30:
        return None
    return best[0]


def _scene_image_for_ref_frame(
    asset: LibraryAsset,
    *,
    preferred_key: str | None = None,
    force_preferred: bool = False,
) -> tuple[str, bytes, str] | None:
    """Use the Agent-selected scene angle, with neutral plates as fallback only."""
    from ...core.library.images import resolve_asset_image

    files = dict(asset.files or {})

    def _is_bad_layout_angle(key: str) -> bool:
        kl = (key or "").lower()
        return any(
            x in kl
            for x in (
                "left_side",
                "right_side",
                "back_view",
                "birds",
                "bird_eye",
                "low_angle",
                "h270",
                "h180",
                "h90",
                "vm30",
            )
        )

    ordered_keys: list[str] = []
    # A rear/side/bird's-eye plate hides the vehicle's driver area and front, so
    # the layout model invents a cab, windows, and a steering wheel to fill the
    # gap. Honor an explicit preferred_key only when it is a usable layout angle;
    # otherwise let the clean full plate win (the bad key still falls through to
    # the last-resort bucket below). ``force_preferred`` overrides the bad-angle
    # filter when the shot itself explicitly asked for that camera angle.
    if preferred_key and (force_preferred or not _is_bad_layout_angle(preferred_key)):
        ordered_keys.append(preferred_key)
    for key in (
        "input_scene",  # clean full plate — best for layout quality
        "master",
        "plate",
        "image",
        "scene",
        "angle_00",
        "angle_0",
    ):
        if key and key in files and files[key] and key not in ordered_keys:
            ordered_keys.append(key)
    frontal: list[str] = []
    rest: list[str] = []
    for k in sorted(files.keys()):
        if not files.get(k) or k in ordered_keys or str(k).startswith("input_"):
            continue
        if _is_bad_layout_angle(k):
            rest.append(k)  # last resort only
            continue
        kl = k.lower()
        if any(x in kl for x in ("front", "wide", "establishing")):
            frontal.append(k)
        else:
            rest.append(k)
    ordered_keys.extend(frontal)
    ordered_keys.extend(rest)

    for key in ordered_keys:
        hit = resolve_asset_image(asset, role="scene", file_key=key)
        if hit:
            name, data, used = hit
            return name, data, used
    return None


def _actor_image_for_ref_frame(
    asset: LibraryAsset,
    *,
    preferred_key: str | None = None,
) -> tuple[str, bytes, str] | None:
    """
    Identity still for layout reference-frame.

    Priority:
    1) Quadrupeds: the full-body sheet front panel, because a quadruped's single
       ``master``/``bust_threeview`` can be an anthropomorphic upright render while
       the sheet carries the true on-all-fours anatomy.
    2) ``bust_threeview`` front panel — the chest-up view keeps hats, headwear,
       and facial identity that a small full-body panel loses.
    3) An explicit non-sheet key, then ``master``/portrait.
    4) Remaining three-view sheets, front-panel cropped.

    Qwen Image Edit Plus copies multi-panel turnaround structure into the output,
    so sheets are always reduced to their front panel.
    """
    from ...core.library.images import resolve_asset_image
    from ...pipelines.actor.workflow import SPECIES_QUADRUPED, actor_prompt_identity

    _, species = actor_prompt_identity(asset.meta or {})
    files = dict(asset.files or {})

    def _sheet_front_crop(
        name: str, data: bytes, used: str, *, force: bool
    ) -> tuple[str, bytes, str] | None:
        cropped = _crop_sheet_front_panel(data, force=force)
        if cropped:
            return cropped[0], cropped[1], f"{used}->front_crop"
        return None

    # An explicit key only counts when the asset actually declares it: the
    # resolver otherwise falls back to any on-disk image, which would force-crop
    # a plain portrait as if it were a turnaround sheet.
    def _declared(key: str) -> bool:
        return bool(files.get(key))

    # 1) Quadrupeds: a master/bust can be an anthropomorphic upright render, so
    # the turnaround sheet's front panel wins first and Layouts use the real
    # on-all-fours animal. This must precede the bust branch below, otherwise a
    # cat that also has a ``bust_threeview`` would resolve to the bust panel and
    # a requested ``fullbody_threeview`` would be reported as unreadable.
    if species == SPECIES_QUADRUPED and preferred_key != "input_actor":
        for key in ("fullbody_threeview", "asset_sheet"):
            if not _declared(key):
                continue
            hit = resolve_asset_image(asset, role="actor", file_key=key)
            if not hit:
                continue
            name, data, used = hit
            return _sheet_front_crop(name, data, used, force=True) or (name, data, used)

    # 2) Face / headwear view: keep hats and facial identity for the Layout.
    if _declared("bust_threeview"):
        hit = resolve_asset_image(asset, role="actor", file_key="bust_threeview")
        if hit:
            name, data, used = hit
            return _sheet_front_crop(name, data, used, force=True) or (name, data, used)

    # 3) Explicit non-sheet keys first
    for key in (
        preferred_key,
        "master",
        "portrait",
        "hero",
        "input_actor",
    ):
        if not key or not _declared(key):
            continue
        hit = resolve_asset_image(asset, role="actor", file_key=key)
        if hit:
            name, data, used = hit
            # If someone stored a sheet under master, still try crop
            if used in ("fullbody_threeview", "bust_threeview", "asset_sheet"):
                cropped = _sheet_front_crop(name, data, used, force=False)
                if cropped:
                    return cropped
            return name, data, used

    # 4) Sheet keys: always try front-panel crop (force — aspect may be only ~1.5)
    for key in ("fullbody_threeview", "bust_threeview", "asset_sheet"):
        if not _declared(key):
            continue
        hit = resolve_asset_image(asset, role="actor", file_key=key)
        if not hit:
            continue
        name, data, used = hit
        return _sheet_front_crop(name, data, used, force=True) or (name, data, used)

    hit = resolve_asset_image(asset, role="actor")
    if not hit:
        return None
    name, data, used = hit
    if used in ("fullbody_threeview", "bust_threeview", "asset_sheet") or "three" in (
        used or ""
    ):
        cropped = _sheet_front_crop(name, data, used, force=True)
        if cropped:
            return cropped
    return name, data, used
