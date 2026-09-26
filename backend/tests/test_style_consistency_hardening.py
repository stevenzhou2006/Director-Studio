from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from app.agents.director.reference_service import match_scene_angle_plate
from app.agents.director.visual_direction import (
    SCENE_STYLE_DERIVATION_PROMPT,
    _analysis_prompt,
    analyze_ref_frame,
    derive_scene_style_sentence,
)
from app.core.projects.models import Project, ProjectMode, Shot, ShotStatus
from app.core.projects.store import save_project
from app.core.prompting import (
    STYLE_CONTRADICTION_MARKER,
    append_style_contradiction_override,
    style_contradiction_terms,
)
from app.core.schemas import LibraryAsset


def _project(style_lock: str = "") -> Project:
    return Project(
        id="prj_hard_1",
        name="p",
        script_text="水墨与青绿设色融合",
        mode=ProjectMode.director,
        style_lock=style_lock,
        created_at="x",
        updated_at="x",
    )


def _shot(**overrides) -> Shot:
    base = dict(
        id="sht_hard_1",
        project_id="prj_hard_1",
        scene_id="scn_1",
        title="Line 1",
        script_beat="dali recites the first line",
        duration_s=3.0,
        status=ShotStatus.draft,
    )
    base.update(overrides)
    return Shot(**base)


# ---------------------------------------------------------------------------
# 2. Deterministic contradiction guard
# ---------------------------------------------------------------------------


def test_contradiction_terms_detect_media_not_in_lock():
    assert style_contradiction_terms(
        "a courtyard rendered in Chinese ink-wash with 青绿 wash",
        "photorealistic cinematic render, soft daylight",
    ) == ["ink-wash painting", "blue-green (青绿) mineral wash"]
    # Lock that itself names the medium: no contradiction.
    assert (
        style_contradiction_terms(
            "ink-wash painting of a courtyard", "Chinese ink-wash 水墨 style"
        )
        == []
    )
    # No lock: guard is inert.
    assert style_contradiction_terms("ink-wash everything", "") == []


def test_contradiction_override_appends_only_when_needed():
    base = "Wide shot rendered in ink-wash with blue-green wash."
    merged = append_style_contradiction_override(base, "photorealistic cinematic")
    assert STYLE_CONTRADICTION_MARKER in merged
    assert "ink-wash painting" in merged
    # Already-guarded prompts are not double-guarded.
    twice = append_style_contradiction_override(merged, "photorealistic cinematic")
    assert twice.count(STYLE_CONTRADICTION_MARKER) == 1
    # No contradiction: unchanged.
    assert (
        append_style_contradiction_override("photoreal courtyard", "photorealistic")
        == "photoreal courtyard"
    )


@pytest.mark.asyncio
async def test_analyze_ref_frame_appends_contradiction_guard(tmp_projects_dir):
    save_project(_project(style_lock="photorealistic cinematic render"))
    brief_payload = {
        "shot_type": "wide shot",
        "camera": "eye level",
        "scene_lock": ["misty courtyard in ink-wash with 青绿 wash"],
        "characters": [
            {
                "reference_image": "Image2",
                "frame_position": "center-left",
                "body_angle": "front",
                "head_direction": "camera",
                "pose": "sitting",
                "interaction": "none",
                "identity_lock": ["same tabby face"],
                "wardrobe_lock": ["natural coat, no clothing"],
            }
        ],
        "forbidden": ["humans"],
        "generation_prompt": (
            "Wide shot of the courtyard from Image1 in ink-wash style with "
            "dali from Image2 sitting center-left."
        ),
    }

    class _VisionClient:
        async def chat(self, model, prompt, **kwargs):
            return json.dumps(brief_payload)

    result = await analyze_ref_frame(
        _shot(),
        images={
            "ref_0": ("scene.png", _jpeg_bytes()),
            "ref_1": ("actor.png", _jpeg_bytes()),
        },
        captions=[
            "Image1 SCENE environment (courtyard, master)",
            "Image2 CHARACTER (dali, fullbody_threeview)",
        ],
        model="test-model",
        ollama=_VisionClient(),
    )
    assert STYLE_CONTRADICTION_MARKER in result.compiled_prompt
    assert "ink-wash painting" in result.compiled_prompt


# ---------------------------------------------------------------------------
# 3. Repair-flow style re-anchor + scene grounding instructions
# ---------------------------------------------------------------------------


def test_repair_review_block_reanchors_medium():
    prompt = _analysis_prompt(
        _shot(),
        ["Image1 SCENE environment", "Image2 CHARACTER (dali)"],
        review_image_used=True,
        feedback="style drifted",
        style_lock="photorealistic cinematic render",
    )
    assert "NOT part of 'what already works'" in prompt
    assert "re-assert the correct medium" in prompt


def test_scene_authority_block_forbids_invented_traditional_medium():
    prompt = _analysis_prompt(
        _shot(),
        ["Image1 SCENE environment", "Image2 CHARACTER (dali)"],
        style_lock="",
    )
    assert "ACTUALLY shows" in prompt
    assert "never call it ink-wash" in prompt


# ---------------------------------------------------------------------------
# 4. Angle-matched scene plate selection
# ---------------------------------------------------------------------------


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (120, 160, 120)).save(buf, format="JPEG")
    return buf.getvalue()


def _scene_asset() -> LibraryAsset:
    return LibraryAsset(
        id="scn_1",
        kind="scenes",
        name="courtyard",
        pipeline_id="scene",
        job_id="job_1",
        created_at="x",
        files={
            "master": "master.jpeg",
            "courtyard_01_left_side_view_h270_v0": "a.png",
            "courtyard_02_back_view_h180_v0": "b.png",
            "courtyard_03_right_side_view_h90_v0": "c.png",
            "courtyard_04_front_left_view_h315_v0": "d.png",
            "courtyard_05_front_right_view_h45_v0": "e.png",
            "courtyard_06_front_view_birds_eye_view_h0_v45": "f.png",
            "courtyard_07_front_view_low_angle_h0_vm30": "g.png",
        },
        meta={},
    )


def test_angle_plate_matching():
    asset = _scene_asset()
    assert (
        match_scene_angle_plate(
            asset, _shot(camera_angle="reverse angle from behind the cats")
        )
        == "courtyard_02_back_view_h180_v0"
    )
    assert (
        match_scene_angle_plate(asset, _shot(camera_angle="bird's eye overview"))
        == "courtyard_06_front_view_birds_eye_view_h0_v45"
    )
    assert (
        match_scene_angle_plate(asset, _shot(camera_angle="low angle looking up"))
        == "courtyard_07_front_view_low_angle_h0_vm30"
    )
    assert (
        match_scene_angle_plate(asset, _shot(composition="front-left three quarter"))
        == "courtyard_04_front_left_view_h315_v0"
    )
    # No explicit angle signal: keep the existing neutral-plate priority.
    assert match_scene_angle_plate(asset, _shot()) is None
    assert match_scene_angle_plate(asset, _shot(camera_angle="eye level")) is None


# ---------------------------------------------------------------------------
# 1. Scene style derivation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derive_scene_style_sentence():
    class _VisionClient:
        async def chat(self, model, prompt, **kwargs):
            assert prompt is SCENE_STYLE_DERIVATION_PROMPT
            return json.dumps(
                {
                    "style_sentence": "Photorealistic cinematic render, soft "
                    "diffused daylight, muted greens with vermilion accents."
                }
            )

    sentence = await derive_scene_style_sentence(
        _jpeg_bytes(), model="test-model", ollama=_VisionClient()
    )
    assert sentence.startswith("Photorealistic cinematic render")


# ---------------------------------------------------------------------------
# 5. Style QC prompt + model
# ---------------------------------------------------------------------------


def test_style_scene_qc_prompt_variants():
    from app.agents.director.service import LayoutStyleQC, _style_scene_qc_prompt

    with_scene = _style_scene_qc_prompt("", has_scene_image=True)
    assert "Image2 is the scene reference plate" in with_scene
    assert "geography_matches" in with_scene
    lock_only = _style_scene_qc_prompt("photorealistic cinematic", has_scene_image=False)
    assert "PROJECT STYLE LOCK is: photorealistic cinematic" in lock_only
    qc = LayoutStyleQC.model_validate(
        {
            "medium_matches": False,
            "geography_matches": True,
            "medium_mismatch": "ink-wash illustration vs photoreal",
            "geography_mismatch": "",
            "passed": False,
            "notes": "",
        }
    )
    assert qc.passed is False
