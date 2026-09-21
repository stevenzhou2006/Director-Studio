"""ComfyUI graph fill for Qwen actor asset workbench.

Policy (simple workbench path):
- Optional **actor reference image** is fed into **master (人像)** and **full-body three-view**.
- One description text (no separate body/hair authority tracks).
- Three-view = workbench multipanel once (image1=master, image2=actor ref).
- Bust three-view = crop of the multipanel sheet (no second KSampler).
"""

from __future__ import annotations

import base64
import copy
import json
import random
from typing import Any

from ...config import settings
from ...core.schemas import ComfyImageRef

# --- Inputs (user-facing) ---
NODE_DESCRIPTION = "58"  # Actor Description
NODE_BODY = "59"  # Body Description (optional)
NODE_HAIR = "60"  # Hairstyle description (optional, text authority)
NODE_ACTOR_IMAGE = "15"  # optional; blank 1x1 → text path
NODE_WARDROBE_IMAGE = "23"  # optional; blank 1x1 → keep original wardrobe
NODE_WARDROBE_EXTRACT_PROMPT = "50"
NODE_NEGATIVE = "11"
NODE_REF_BASE_PROMPT = "63"  # actor ref → master base

# Auto switches are driven by image size (width > 1); do not set manually:
# 22 actor source, 30 wardrobe apply, 56 extract wardrobe

# Bust sampler chain removed at fill time (no secondary sampling)
SEED_NODES = ("13", "20", "28", "44", "54")  # no "37" bust sampler
BUST_SAMPLER_NODES = ("33", "34", "35", "36", "37", "38")

SAVE_NODES = {
    "57": "wardrobe_ref",
    "31": "master",
    "39": "bust_threeview",
    "46": "fullbody_threeview",
    "48": "asset_sheet",
}

OUTPUT_LABELS = {
    "wardrobe_ref": "00 · Wardrobe Reference",
    "master": "01 · Actor Master",
    "bust_threeview": "02 · Bust Three-view",
    "fullbody_threeview": "03 · Full-body Three-view",
    "asset_sheet": "04 · Asset Sheet",
}

# Optional-image placeholder. The graph ships with a legacy filename, but the
# file is never bundled into ComfyUI's input folder, so LoadImage validation
# rejects it. Director Studio now uploads a real 1×1 PNG per job and points the
# LoadImage nodes at that uploaded name. Presence routing stays size-based:
# width > 1 ⇒ real reference upload. BLANK_IMAGE remains the legacy graph name
# for callers that build a prompt without an uploaded blank.
BLANK_IMAGE = "qwen_actor_asset_blank.ppm"
BLANK_INPUT_KEY = "actor_blank"
BLANK_INPUT_FILENAME = "actor_blank.png"

# 1×1 fully transparent PNG. Valid for ComfyUI PIL-based LoadImage and small
# enough that width/height stay 1, which is what the graph's auto-switch reads.
_BLANK_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def blank_placeholder() -> tuple[str, bytes]:
    """Return ``(filename, bytes)`` for the optional-reference placeholder."""
    return BLANK_INPUT_FILENAME, _BLANK_PNG_BYTES

# Baseline negative from working job 008126d9, minus "side view" (kills 3/4 panels)
# and without footwear bans — shoes vs bare feet come from user description / master text.
DEFAULT_NEGATIVE = (
    "cropped body, multiple people, duplicate body, extra limbs, missing limbs, "
    "deformed hands, malformed fingers, deformed feet, "
    "dramatic pose, text, watermark, collage, cluttered background, blur, "
    "inconsistent hairstyle across panels, wrong rear hairstyle, "
    "inventing a bun when hair is described as loose, converting loose hair to updo"
)

DEFAULT_DESCRIPTION = (
    "Photorealistic professional actor casting reference, one adult, "
    "front-facing complete full-body studio portrait, eye-level camera, "
    "standing upright in a neutral relaxed symmetrical pose, both arms naturally at sides, "
    "entire body visible head to toe, plain seamless white studio background, "
    "soft even lighting, exactly one person, no text, no collage. "
    "Specify age, face vibe, hair, outfit, footwear, and body build in this text."
)

# Node ids for three-view base prompts in qwen_actor_asset_workbench.api.json
NODE_FULLBODY_THREEVIEW_PROMPT = "66"
NODE_BUST_THREEVIEW_PROMPT = "68"  # unused when bust is crop-only; kept for compatibility

# Workbench multipanel three-view (nodes 40–45, prompts 66–67). Kept intact.
# Dynamic per-view node ids (200–281) are stripped if present so we never dual-run.
_DYNAMIC_PER_VIEW_IDS = tuple(str(i) for i in range(200, 282))

# Workbench full-body three-view canvas (3 equal panels)
_TV_SHEET_W = 2880
_TV_SHEET_H = 1920
_TV_BUST_H = 960

# --- Species awareness ---
# "human" keeps the original casting persona. "quadruped" swaps every pose /
# anatomy clause so an animal reference is not humanized by the base prompts.
SPECIES_HUMAN = "human"
SPECIES_QUADRUPED = "quadruped"
SPECIES_AUTO = "auto"

_QUADRUPED_HINTS = (
    "cat", "cats", "kitten", "dog", "dogs", "puppy", "fox", "wolf", "tiger",
    "lion", "leopard", "cheetah", "panther", "puma", "jaguar", "rabbit",
    "bunny", "ferret", "raccoon", "panda", "bear", "deer", "horse", "pony",
    "monkey", "ape", "fennec", "tabby", "siamese", "persian", "sphynx",
    "quadruped", "four-legged", "four legged", "on all fours", "on all four",
    "paw", "paws", "tail", "animal", "狸花猫", "猫", "狗", "狐狸", "兔子",
    "熊猫", "老虎", "狮子", "马", "猴", "动物", "四足",
)


def detect_species(text: str) -> str:
    """Keyword-based species detection from the actor description."""
    lowered = (text or "").lower()
    if any(hint in lowered for hint in _QUADRUPED_HINTS):
        return SPECIES_QUADRUPED
    return SPECIES_HUMAN


def resolve_species(species: str | None, description: str) -> str:
    if species == SPECIES_QUADRUPED:
        return SPECIES_QUADRUPED
    if species == SPECIES_HUMAN:
        return SPECIES_HUMAN
    return detect_species(description)


def resolve_actor_identity(params: dict[str, Any]) -> tuple[str, str]:
    """Return the generation-resolved ``(species, description)`` for an actor job.

    ``build_actor_prompt`` substitutes a species-appropriate default when no
    description is supplied, but the raw job params (and therefore the saved
    library meta) used to keep the human boilerplate even for quadrupeds. That
    leaked a "one adult ... exactly one person" identity into every downstream
    Layout prompt, so the persisted identity is resolved here to match what was
    actually rendered.
    """
    description = str((params or {}).get("description") or "").strip()
    species = resolve_species((params or {}).get("species"), description)
    if species == SPECIES_QUADRUPED and (
        not description or description == DEFAULT_DESCRIPTION.strip()
    ):
        # The human casting boilerplate ("standing upright ... both arms ...
        # exactly one person") must never ride along on a quadruped, or the
        # master renders as an anthropomorphic upright animal.
        description = DEFAULT_QUADRUPED_DESCRIPTION
    elif not description:
        description = DEFAULT_DESCRIPTION
    return species, description


def actor_prompt_identity(meta: dict[str, Any] | None) -> tuple[str, str]:
    """Return ``(appearance, species)`` for prompts and catalogs.

    Human actors are returned untouched. For a quadruped, the generic human
    casting boilerplate ("one adult ... exactly one person") is dropped so the
    animal is never described as a person. Species is read from stored meta with
    a description keyword fallback.
    """
    appearance = str((meta or {}).get("description") or "").strip()
    species = resolve_species((meta or {}).get("species"), appearance)
    if species == SPECIES_QUADRUPED:
        if appearance == DEFAULT_DESCRIPTION.strip():
            appearance = ""
        if not appearance:
            appearance = DEFAULT_QUADRUPED_DESCRIPTION
    return appearance, species


# Quadruped master base: same structure as the human one, animal anatomy.
REF_QUADRUPED_MASTER_PROMPT = (
    "Image 1 is the animal actor REFERENCE. Preserve the same animal: face identity, "
    "ear shape, eye color, nose, coat/fur color and pattern, body build, tail, and "
    "overall look exactly as visible. Normalize into a photorealistic professional "
    "animal actor casting master: front-facing complete full-body studio portrait, "
    "camera at the animal's own eye level, natural quadruped stance on all four paws, "
    "weight even on all legs, tail fully visible and hanging or curled naturally, "
    "head to tail-tip and paw pads visible with margin, plain seamless white studio "
    "background, soft even lighting. "
    "If the reference is a close-up face only, invent a natural quadruped body "
    "consistent with that face and the written description (do not invent a different "
    "animal). Do NOT stand the animal upright on two legs; no hands, no thumbs, no "
    "anthropomorphic posture. "
    "Outfit and footwear: follow the USER DESCRIPTION below when it specifies "
    "clothing, harness or bare coat; otherwise keep the animal unclothed with its "
    "natural coat. Exactly one animal, no text, no collage, no props."
)

# Quadruped master base for the TEXT path (no actor reference image). The ref-path
# prompt above starts with "Image 1 is the animal actor REFERENCE", which does not
# apply when the master comes from text alone. Without this block the text path
# (node 58 → 62 → 10) ignores species=quadruped and renders the workflow's default
# human pose.
TEXT_QUADRUPED_MASTER_PROMPT = (
    "The subject is a quadruped animal, NOT a human. Create one photorealistic "
    "professional animal actor casting master: front-facing complete full-body "
    "studio portrait of the exact animal described below, camera at the animal's own "
    "eye level, natural quadruped stance on all four paws, weight even on all legs, "
    "tail fully visible and hanging or curled naturally, head to tail-tip and paw "
    "pads visible with margin, plain seamless white studio background, soft even "
    "lighting. Preserve the described species, face, ear shape, eye color, nose, "
    "coat/fur color and pattern, body build, and tail. "
    "Do NOT stand the animal upright on two legs; no hands, no thumbs, no human "
    "anatomy, no anthropomorphic posture, no bipedal stance. "
    "Outfit and footwear: follow the USER DESCRIPTION below when it specifies "
    "clothing, harness or bare coat; otherwise keep the animal unclothed with its "
    "natural coat. Exactly one animal, no text, no collage, no props."
)

# Fallback when species is quadruped but no description text was supplied.
DEFAULT_QUADRUPED_DESCRIPTION = (
    "a natural quadruped animal matching the requested species, on all four paws"
)

# Appended when the actor needs no wardrobe (e.g. an animal with its natural
# coat). Overrides any clothing the description may mention and feeds the
# negative prompt so the master and three-view stay unclothed.
NO_WARDROBE_INSTRUCTION = (
    "WARDROBE: NONE — this actor has no outfit. Do not add or keep any clothing, "
    "outfit, costume, robe, dress, uniform, harness, collar, leash, shoes, "
    "footwear, hat, headwear, jewelry, or wearable accessories, even if the "
    "description above mentions them. Render only the natural body or animal coat."
)

# Human master base (ref path). User Description is appended at build time — it
# controls outfit/footwear when stated (e.g. bare feet vs shoes).
REF_ACTOR_MASTER_PROMPT = (
    "Image 1 is the actor REFERENCE photo. Preserve the same person: face identity, "
    "hairstyle, hair color/length, body build as visible, age and overall look. "
    "Normalize into a photorealistic professional actor casting master: front-facing complete "
    "full-body studio portrait, eye-level, upright symmetrical stance, arms at sides, "
    "head to toe with margin, plain seamless white studio background, soft even lighting. "
    "If the reference is a close-up face only, invent a natural full body consistent with that "
    "face and the written description (do not invent a different person). "
    "Outfit and footwear: follow the USER DESCRIPTION below when it specifies clothing or "
    "bare feet / shoes; otherwise keep clear clothes from image 1, else simple neutral studio wear. "
    "Exactly one person, no text, no collage, no props."
)

# Alias kept for older tests/imports
REF_FACE_ONLY_MASTER_PROMPT = REF_ACTOR_MASTER_PROMPT

# Three-view: multipanel (008126d9 baseline). Footwear follows master (no forced shoes).
_FULLBODY_THREEVIEW_PROMPT_TEMPLATE = (
    "Image 1 is the actor MASTER (full-body front). "
    "Image 2 is the original actor REFERENCE photo — keep the same person identity "
    "(face, hair, body vibe) consistent with image 1 and image 2. "
    "Create one wide professional actor turnaround sheet: exactly THREE equal vertical panels "
    "with clean white separators — and ONLY three figures total (one per panel). "
    "FORBIDDEN: more than three people, extra clones, a row of extra backs, six-panel grids, "
    "duplicated bodies, or extra mini-figures between panels. "
    "Every panel: complete body head to toe, upright neutral pose, arms at sides. "
    "Keep the same hairstyle and body as the master across all panels. "
    "{wardrobe_instruction} {headwear_instruction} "
    "LEFT: exact front view. CENTER: right-facing 45-degree three-quarter. "
    "RIGHT: exact back view. "
    "Same scale, eye-level, light-gray studio background, accurate hands and feet. "
    "No text, labels, crop, or clothing changes between panels."
)

_FULLBODY_THREEVIEW_QUADRUPED_TEMPLATE = (
    "Image 1 is the animal actor MASTER (full-body front). "
    "Image 2 is the original animal REFERENCE photo — keep the same animal identity "
    "(face, ears, coat pattern, body vibe) consistent with image 1 and image 2. "
    "Create one wide professional animal turnaround sheet: exactly THREE equal panels "
    "with clean white separators — and ONLY three figures total (one per panel). "
    "FORBIDDEN: more than three animals, extra clones, a row of extra backs, six-panel grids, "
    "duplicated bodies, or extra mini-figures between panels. "
    "Every panel: the same animal in a natural quadruped stance on all four paws, "
    "tail fully visible, never standing upright on two legs, no hands, no thumbs, "
    "no anthropomorphic posture. "
    "Keep the same coat, markings, paws, and tail as the master across all panels. "
    "{wardrobe_instruction} {headwear_instruction} "
    "LEFT: exact front view. CENTER: right-facing side profile. "
    "RIGHT: exact back view showing the full back coat and tail. "
    "Same scale, camera at the animal's eye level, light-gray studio background, "
    "accurate paws and legs. No text, labels, crop, or clothing changes between panels."
)


def _fullbody_threeview_prompt(
    *,
    include_headwear: bool,
    species: str = SPECIES_HUMAN,
    include_wardrobe: bool = True,
) -> str:
    if include_headwear:
        headwear_instruction = (
            "The same hat or headwear visible on the master must appear in all three panels, "
            "with identical shape, color, trim, and placement"
        )
    elif species == SPECIES_QUADRUPED:
        headwear_instruction = "No hat, collar, or headwear in any panel"
    else:
        headwear_instruction = "No hat or headwear in any panel"
    if not include_wardrobe:
        wardrobe_instruction = (
            "No clothing, harness, collar, shoes, or wearable accessories in any panel "
            "— natural coat only."
            if species == SPECIES_QUADRUPED
            else "No clothing or wearable accessories in any panel."
        )
    elif species == SPECIES_QUADRUPED:
        wardrobe_instruction = "Keep any clothing or harness from the master across all panels."
    else:
        wardrobe_instruction = "Keep the same clothing and footwear as the master across all panels."
    template = (
        _FULLBODY_THREEVIEW_QUADRUPED_TEMPLATE
        if species == SPECIES_QUADRUPED
        else _FULLBODY_THREEVIEW_PROMPT_TEMPLATE
    )
    return template.format(
        headwear_instruction=headwear_instruction,
        wardrobe_instruction=wardrobe_instruction,
    )


FULLBODY_THREEVIEW_PROMPT = _fullbody_threeview_prompt(include_headwear=False)
BUST_THREEVIEW_PROMPT = (
    "Bust three-view is produced by cropping the full-body three-view (no second sample). "
    "Upper strip of the three panels: front | three-quarter | back head-and-shoulders."
)


def _strip_dynamic_per_view_nodes(prompt: dict[str, Any]) -> None:
    """Remove experimental per-view/hair-fix nodes if a graph was previously patched."""
    for nid in _DYNAMIC_PER_VIEW_IDS:
        prompt.pop(nid, None)


def _use_workbench_multipanel_threeview(
    prompt: dict[str, Any],
    *,
    include_headwear: bool,
    species: str = SPECIES_HUMAN,
    include_wardrobe: bool = True,
) -> None:
    """
    Keep qwen_actor_asset_workbench multipanel three-view:
      encode 40 (image1=master 30, image2=actor ref 15) → sample → decode 45 → save 46
    Bust = crop 32 from 45; no second bust sampler.
    """
    _strip_dynamic_per_view_nodes(prompt)
    for nid in BUST_SAMPLER_NODES:
        prompt.pop(nid, None)

    if NODE_FULLBODY_THREEVIEW_PROMPT in prompt:
        prompt[NODE_FULLBODY_THREEVIEW_PROMPT]["inputs"]["value"] = (
            _fullbody_threeview_prompt(
                include_headwear=include_headwear,
                species=species,
                include_wardrobe=include_wardrobe,
            )
        )
    if NODE_BUST_THREEVIEW_PROMPT in prompt:
        prompt[NODE_BUST_THREEVIEW_PROMPT]["inputs"]["value"] = BUST_THREEVIEW_PROMPT

    # Master + original reference into three-view
    if "40" in prompt:
        prompt["40"]["inputs"]["image1"] = ["30", 0]
        prompt["40"]["inputs"]["image2"] = [NODE_ACTOR_IMAGE, 0]
        if "67" in prompt:
            prompt["40"]["inputs"]["prompt"] = ["67", 0]

    if "46" in prompt:
        prompt["46"]["inputs"]["images"] = ["45", 0]

    if "32" in prompt:
        prompt["32"]["inputs"]["image"] = ["45", 0]
        prompt["32"]["inputs"]["width"] = _TV_SHEET_W
        prompt["32"]["inputs"]["height"] = _TV_BUST_H
        prompt["32"]["inputs"]["x"] = 0
        prompt["32"]["inputs"]["y"] = 0
    if "39" in prompt:
        prompt["39"]["inputs"]["images"] = ["32", 0]
        prompt["39"]["_meta"] = {
            **(prompt["39"].get("_meta") or {}),
            "title": "Save Bust Three-View (crop, no resample)",
        }
    if "47" in prompt:
        prompt["47"]["inputs"]["image_1"] = ["32", 0]
        prompt["47"]["inputs"]["image_2"] = ["45", 0]


WARDROBE_EXTRACT_PROMPT = (
    "Extract the complete coordinated outfit from the subject in the source image and present it "
    "as a clean product-style wardrobe reference on a plain neutral background. Preserve garment "
    "silhouette, construction, layers, material, colors, trim, patterns, closures, and visible wear. "
    "Exclude the subject's face, hair or fur, body, pose, hands or paws, jewelry, handheld objects, "
    "and background. "
    "{headwear} {footwear} Exactly one coordinated wardrobe set, no person or animal, no text, "
    "no collage."
)


def _wardrobe_extract_prompt(
    *, include_headwear: bool, include_footwear: bool
) -> str:
    headwear = (
        "Include clearly visible hat or headwear as part of the coordinated look; preserve its exact "
        "type, silhouette, material, color, trim, and placement."
        if include_headwear
        else "Exclude headwear."
    )
    footwear = (
        "Include clearly visible shoes or boots as one matched pair; preserve their exact category, "
        "shape, color, material, sole, heel, closures, and distinctive wear."
        if include_footwear
        else "Exclude shoes and other footwear."
    )
    return WARDROBE_EXTRACT_PROMPT.format(headwear=headwear, footwear=footwear)


def _wardrobe_transfer_prompt(
    *,
    include_headwear: bool,
    include_footwear: bool,
    species: str = SPECIES_HUMAN,
) -> str:
    headwear = (
        "Apply the hat or headwear from image 2, preserving its exact design and fit; keep the actor's "
        "identity and visible hair consistent around and beneath it."
        if include_headwear
        else "Preserve the master hairstyle and do not add headwear."
    )
    footwear = (
        "Apply the exact footwear from image 2 as a matched pair, preserving its design, "
        "material, and color."
        if include_footwear
        else "Preserve image 1's feet and footwear; if the master is barefoot, keep it "
        "barefoot, and if it wears shoes, keep equivalent shoes."
    )
    if species == SPECIES_QUADRUPED:
        headwear = (
            "Apply the hat or headwear from image 2, preserving its exact design and fit over the "
            "animal's ears and head."
            if include_headwear
            else "Preserve the master's head, ears, and coat and do not add headwear or collars."
        )
        footwear = (
            "Apply the exact footwear from image 2 as a matched set on all paws, preserving its "
            "design, material, and color."
            if include_footwear
            else "Preserve image 1's paws bare; do not add shoes."
        )
        return (
            "Image 1 is the target animal actor master — LOCK its face, identity, quadruped "
            "anatomy, leg length, body proportions, stance on all four paws, tail, and pose. "
            "Image 2 is a wardrobe reference containing garments and only the explicitly selected "
            "wearable accessories. Image 3 is the original animal reference; use it for identity "
            "only, preserving the same facial features, ear shape, and coat pattern. Do not copy "
            "clothing, pose, framing, or background from image 3. Re-dress image 1 with the "
            "garments from image 2, tailored to the animal's quadruped body so that all four legs, "
            "paws, and the tail remain visible and natural; never stand the animal upright. "
            f"{headwear} {footwear} Ignore the garment source's face, fur, body, and pose. "
            "Exactly one front-facing complete full-body animal in natural quadruped stance, "
            "plain white studio background, no text."
        )
    return (
        "Image 1 is the target actor master — LOCK its face, identity, body proportions, and pose. "
        "Image 2 is a wardrobe reference containing garments and only the explicitly selected "
        "wearable accessories. Image 3 is the original actor reference; use it for identity only, "
        "preserving the same facial features and distinctive identity. Do not copy clothing, pose, "
        "framing, or background from image 3. Re-dress image 1 with the garments from image 2. "
        f"{headwear} {footwear} Ignore the clothing model's face, hair, body, and pose. "
        "Exactly one front-facing complete full-body actor, plain white studio background, no text."
    )

WORKFLOW_FILENAME = "qwen_actor_asset_workbench.api.json"

LEAF_PREFIX = {
    "wardrobe_ref": "00_wardrobe_reference",
    "master": "01_actor_master",
    "bust_threeview": "02_bust_threeview",
    "fullbody_threeview": "03_fullbody_threeview",
    "asset_sheet": "04_actor_asset_sheet",
}


def load_base_prompt() -> dict[str, Any]:
    path = settings.workflows_dir / WORKFLOW_FILENAME
    if not path.exists():
        path = settings.workflow_path
    if not path.exists():
        raise FileNotFoundError(f"Workflow API JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_actor_prompt(
    *,
    description: str = "",
    body_description: str = "",
    hair_description: str = "",
    negative_prompt: str = "",
    actor_image_name: str | None = None,
    wardrobe_image_name: str | None = None,
    blank_image_name: str | None = None,
    include_headwear: bool = False,
    include_footwear: bool = False,
    include_wardrobe: bool = True,
    species: str = SPECIES_AUTO,
    seed: int | None = None,
    job_id: str | None = None,
) -> tuple[dict[str, Any], int]:
    """
    Patch workbench prompt.

    - No actor image → text-to-actor master
    - Actor image → ref into master (node 15→16) and into three-view (image2)
    - Single description text (legacy body/hair fields ignored / cleared)
    - Full-body three-view: workbench multipanel once
    - Bust three-view: crop of that sheet
    - species: "human" / "quadruped" / "auto" (detect from description)
    """
    prompt = copy.deepcopy(load_base_prompt())
    resolved_seed = seed if seed is not None else random.randint(0, 2**32 - 1)

    # Single description — also injected into ref-path master (node 63), not only text path 58
    resolved_species, desc = resolve_actor_identity(
        {"description": description, "species": species}
    )
    # Text path (node 58 → 62 → 10) has no reference-image base prompt, so the
    # species anatomy must ride in the description itself. Node 63 (ref path) gets
    # its own base below.
    if resolved_species == SPECIES_QUADRUPED:
        text_value = f"{TEXT_QUADRUPED_MASTER_PROMPT}\n\nUSER DESCRIPTION:\n{desc}"
    else:
        text_value = desc
    if not include_wardrobe:
        text_value = f"{text_value}\n\n{NO_WARDROBE_INSTRUCTION}"
    prompt[NODE_DESCRIPTION]["inputs"]["value"] = text_value
    prompt[NODE_BODY]["inputs"]["value"] = ""
    prompt[NODE_HAIR]["inputs"]["value"] = ""

    negative = negative_prompt or DEFAULT_NEGATIVE
    if resolved_species == SPECIES_QUADRUPED:
        negative += (
            ", anthropomorphic, humanoid figure, standing upright on two legs, "
            "human hands, thumbs, human face, bipedal posture"
        )
    if not include_wardrobe:
        negative += (
            ", clothing, clothes, outfit, costume, robe, dress, uniform, harness, "
            "collar, leash, shoes, footwear, hat, headwear, jewelry, accessories"
        )
    prompt[NODE_NEGATIVE]["inputs"]["text"] = negative

    # Master base + user description (outfit/footwear follow description when stated)
    if NODE_REF_BASE_PROMPT in prompt:
        base = (
            REF_QUADRUPED_MASTER_PROMPT
            if resolved_species == SPECIES_QUADRUPED
            else REF_ACTOR_MASTER_PROMPT
        )
        ref_value = f"{base}\n\nUSER DESCRIPTION:\n{desc}"
        if not include_wardrobe:
            ref_value = f"{ref_value}\n\n{NO_WARDROBE_INSTRUCTION}"
        prompt[NODE_REF_BASE_PROMPT]["inputs"]["value"] = ref_value

    # Neutral concat delimiters (body/hair nodes empty; description already in 63)
    for nid in ("61", "62", "64", "65", "67", "69"):
        if nid in prompt:
            prompt[nid]["inputs"]["delimiter"] = "\n\n"

    if "24" in prompt:
        prompt["24"]["inputs"]["prompt"] = _wardrobe_transfer_prompt(
            include_headwear=include_headwear,
            include_footwear=include_footwear,
            species=resolved_species,
        )
        prompt["24"]["inputs"]["image3"] = [NODE_ACTOR_IMAGE, 0]
    if NODE_WARDROBE_EXTRACT_PROMPT in prompt:
        prompt[NODE_WARDROBE_EXTRACT_PROMPT]["inputs"]["prompt"] = (
            _wardrobe_extract_prompt(
                include_headwear=include_headwear,
                include_footwear=include_footwear,
            )
        )

    # Reference image → master path (15) and three-view image2 (same load node).
    # No upload ⇒ point at the per-job 1×1 blank so LoadImage validation passes.
    placeholder = blank_image_name or BLANK_IMAGE
    prompt[NODE_ACTOR_IMAGE]["inputs"]["image"] = actor_image_name or placeholder
    prompt[NODE_WARDROBE_IMAGE]["inputs"]["image"] = wardrobe_image_name or placeholder

    # Ensure master ref encode uses actor image
    if "16" in prompt:
        prompt["16"]["inputs"]["image1"] = [NODE_ACTOR_IMAGE, 0]

    _use_workbench_multipanel_threeview(
        prompt,
        include_headwear=include_headwear,
        species=resolved_species,
        include_wardrobe=include_wardrobe,
    )

    for nid in SEED_NODES:
        if nid in prompt:
            prompt[nid]["inputs"]["seed"] = resolved_seed

    if job_id:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)[:32]
        for nid, key in SAVE_NODES.items():
            if nid in prompt:
                prompt[nid]["inputs"]["filename_prefix"] = (
                    f"director-studio/{safe}/{LEAF_PREFIX.get(key, key)}"
                )

    return prompt, resolved_seed


def map_history_outputs(history: dict[str, Any]) -> dict[str, ComfyImageRef]:
    outputs = history.get("outputs") or {}
    mapped: dict[str, ComfyImageRef] = {}
    for nid, key in SAVE_NODES.items():
        node_out = outputs.get(nid) or outputs.get(str(nid))
        if not node_out:
            continue
        images = node_out.get("images") or []
        if not images:
            continue
        img = images[-1]
        mapped[key] = ComfyImageRef(
            filename=img.get("filename") or "",
            subfolder=img.get("subfolder") or "",
            type=img.get("type") or "output",
        )
    return mapped


def derive_mode(*, has_actor_ref: bool, has_wardrobe_ref: bool) -> str:
    """Display helper only — not sent to Comfy switches."""
    if has_wardrobe_ref:
        return "wardrobe"
    if has_actor_ref:
        return "reference"
    return "text"
