"""Scene multi-angle pipeline: 2511 multi-angle graph and graph hygiene."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image, ImageDraw

from app.config import settings
from app.core.jobs import create_job, save_input_file
from app.pipelines.scene import background
from app.pipelines.scene.pipeline import ScenePipeline
from app.pipelines.scene.workflow import (
    DEFAULT_ANGLES,
    DEFAULT_PREPEND,
    ISOLATED_PREPEND,
    NODE_LIGHTNING,
    NODE_NEGATIVE,
    NODE_PROMPT_LIST,
    NODE_SAMPLER,
    NODE_SAVE,
    VISUAL_WORKFLOW_FILENAME,
    WORKFLOW_FILENAME,
    build_scene_prompt,
    parse_angle_lines,
    visual_workflow_path,
    workflow_path,
)


def test_default_angles_cover_original_quality_view_set():
    lines = parse_angle_lines(DEFAULT_ANGLES)
    assert len(lines) == 7
    assert "horizontal: 270" in lines[0]
    assert "horizontal: 180" in lines[1]
    assert "horizontal: 90" in lines[2]
    assert "horizontal: 315" in lines[3]
    assert "horizontal: 45" in lines[4]
    assert "bird's eye" in lines[5]
    assert "vertical: -30" in lines[6]


def test_build_scene_prompt_uses_quality_canvas_and_scene_latent():
    prompt, seed, used, stems = build_scene_prompt(
        scene_image_name="plate.png",
        scene_name="Audition_Room",
        seed=11,
        job_id="job_scene1",
    )
    assert seed == 11
    assert used == parse_angle_lines(DEFAULT_ANGLES)
    assert stems[0].startswith("Audition_Room_01_")
    assert "left_side" in stems[0]
    pl = prompt[NODE_PROMPT_LIST]["inputs"]
    assert DEFAULT_PREPEND in pl["prepend_text"]
    assert "only change the camera" in pl["prepend_text"].lower()
    assert prompt[NODE_SAMPLER]["inputs"]["latent_image"] == ["105", 0]
    assert prompt["105"]["class_type"] == "VAEEncode"
    assert prompt["105"]["inputs"]["pixels"] == ["107", 0]
    assert prompt["107"]["class_type"] == "ImageScale"
    assert prompt["107"]["inputs"] == {
        "image": ["41", 0],
        "upscale_method": "lanczos",
        "width": 1728,
        "height": 960,
        "crop": "center",
    }
    assert prompt[NODE_NEGATIVE]["class_type"] == "ConditioningZeroOut"
    assert prompt[NODE_LIGHTNING]["inputs"]["strength_model"] == 1.0
    assert prompt[NODE_SAVE]["inputs"]["filename_prefix"].startswith("director-studio/")
    assert prompt[NODE_SAMPLER]["inputs"]["seed"] == 11


def test_explicit_prepend_overrides_default():
    prompt, _, _, _ = build_scene_prompt(
        scene_image_name="plate.png",
        prepend_text="night interior, tungsten practicals",
    )
    assert (
        prompt[NODE_PROMPT_LIST]["inputs"]["prepend_text"]
        == "night interior, tungsten practicals"
    )


def test_scene_api_and_visual_workflows_exist():
    assert workflow_path().name == WORKFLOW_FILENAME
    assert workflow_path().is_file()
    visual = json.loads(visual_workflow_path().read_text(encoding="utf-8"))
    assert visual_workflow_path().name == VISUAL_WORKFLOW_FILENAME
    types = {n["type"] for n in visual["nodes"]}
    assert "LoadImage" in types
    assert "TextEncodeQwenImageEditPlus" in types
    assert "ConditioningZeroOut" in types
    assert "ImageScale" in types
    assert "VAEEncode" in types
    assert "EmptySD3LatentImage" not in types
    assert "SaveImage" in types
    assert "MarkdownNote" in types
    groups = [g["title"] for g in visual["groups"]]
    assert any(t.startswith("1 ·") for t in groups)
    assert any("Output" in t for t in groups)


def _white_cutout_png() -> bytes:
    img = Image.new("RGB", (96, 96), (255, 255, 255))
    ImageDraw.Draw(img).ellipse((24, 24, 72, 72), fill=(30, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def isolated_jobs(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    projects = tmp_path / "projects"
    jobs.mkdir(parents=True, exist_ok=True)
    projects.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "projects_dir", projects)
    return tmp_path


def test_has_no_background_detects_cutouts(tmp_path):
    white = tmp_path / "white.png"
    white.write_bytes(_white_cutout_png())
    assert background.has_no_background(white) is True

    transparent = tmp_path / "alpha.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(transparent)
    assert background.has_no_background(transparent) is True

    scene = tmp_path / "scene.png"
    Image.new("RGB", (32, 32), (90, 120, 150)).save(scene)
    assert background.has_no_background(scene) is False


def test_cut_out_background_keeps_interior_white_and_transparents_border(tmp_path):
    plate = tmp_path / "gen.png"
    img = Image.new("RGB", (120, 80), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((30, 20, 90, 70), fill=(200, 60, 40))
    draw.ellipse((50, 35, 70, 55), fill=(255, 255, 255))
    img.save(plate)

    assert background.cut_out_background(plate) is True
    out = Image.open(plate)
    assert out.mode == "RGBA"
    assert out.getchannel("A").getpixel((2, 2)) == 0
    assert out.getchannel("A").getpixel((40, 30)) == 255
    # White enclosed by the subject stays opaque; only the border is cut.
    assert out.getchannel("A").getpixel((60, 45)) == 255
    # Idempotent: a second pass leaves an already cut image alone.
    assert background.cut_out_background(plate) is False


def test_pipeline_flags_backgroundless_plate(isolated_jobs):
    pipe = ScenePipeline()
    job = create_job(pipeline_id="scene", asset_kind="scenes", name="Actor")
    save_input_file(job.id, "scene", "scene.png", _white_cutout_png())

    pipe.prepare_job_submission(job)
    assert job.params["backgroundless"] is True


def test_pipeline_uses_isolation_prompt_for_backgroundless_job(isolated_jobs):
    pipe = ScenePipeline()
    job = create_job(
        pipeline_id="scene",
        asset_kind="scenes",
        name="Actor",
        params={"backgroundless": True, "prepend_text": "keep the room"},
    )
    prompt, _ = pipe.build_prompt(job, uploaded_images={"scene": "plate.png"})

    assert prompt[NODE_PROMPT_LIST]["inputs"]["prepend_text"] == ISOLATED_PREPEND


def test_pipeline_leaves_scene_jobs_untouched(isolated_jobs):
    pipe = ScenePipeline()
    job = create_job(
        pipeline_id="scene",
        asset_kind="scenes",
        name="Set",
        params={"prepend_text": "keep the room"},
    )
    prompt, _ = pipe.build_prompt(job, uploaded_images={"scene": "plate.png"})

    assert prompt[NODE_PROMPT_LIST]["inputs"]["prepend_text"] == "keep the room"


def test_pipeline_postprocess_cuts_only_backgroundless_outputs(isolated_jobs):
    pipe = ScenePipeline()
    output = isolated_jobs / "out.png"
    Image.new("RGB", (80, 80), (255, 255, 255)).save(output)

    opaque_job = create_job(pipeline_id="scene", asset_kind="scenes", name="Set")
    pipe.postprocess_job_outputs(opaque_job, {"out": str(output)})
    assert Image.open(output).mode == "RGB"

    cutout_job = create_job(
        pipeline_id="scene",
        asset_kind="scenes",
        name="Actor",
        params={"backgroundless": True},
    )
    pipe.postprocess_job_outputs(cutout_job, {"out": str(output)})
    assert Image.open(output).mode == "RGBA"
