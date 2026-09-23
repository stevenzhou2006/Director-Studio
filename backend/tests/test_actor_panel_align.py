"""Quadruped turnaround alignment: equal heights, shared baseline, centring."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.core.jobs import create_job
from app.pipelines.actor import panel_align
from app.pipelines.actor.pipeline import ActorPipeline

PANEL_W = 300
PANEL_H = 600
BG = (233, 234, 235)


def _subject_bbox(panel: Image.Image) -> tuple[int, int, int, int] | None:
    mask = panel.convert("L").point(lambda v: 255 if v < 100 else 0)
    return mask.getbbox()


def _sheet(rects: list[tuple[int, int, int, int]]) -> Image.Image:
    sheet = Image.new("RGB", (PANEL_W * 3, PANEL_H), BG)
    draw = ImageDraw.Draw(sheet)
    for i, (x0, y0, x1, y1) in enumerate(rects):
        draw.rectangle(
            (i * PANEL_W + x0, y0, i * PANEL_W + x1, y1), fill=(30, 30, 30)
        )
    return sheet


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    fullbody = tmp_path / "fullbody.png"
    bust = tmp_path / "bust.png"
    asset = tmp_path / "asset.png"
    return fullbody, bust, asset


def test_normalize_equalizes_height_baseline_and_centre(tmp_path):
    fullbody, bust, asset = _paths(tmp_path)
    # Three subjects with different heights and vertical offsets.
    sheet = _sheet([(100, 100, 200, 500), (120, 200, 180, 450), (90, 50, 210, 400)])
    sheet.save(fullbody)
    # Derived outputs exist; the module rewrites them.
    Image.new("RGB", (PANEL_W * 3, PANEL_H // 2), BG).save(bust)
    Image.new("RGB", (PANEL_W * 3, PANEL_H + PANEL_H // 2), BG).save(asset)

    assert panel_align.normalize_turnaround(fullbody, bust, asset) is True

    out = Image.open(fullbody).convert("RGB")
    assert out.size == (PANEL_W * 3, PANEL_H)
    boxes = [
        _subject_bbox(out.crop((i * PANEL_W, 0, (i + 1) * PANEL_W, PANEL_H)))
        for i in range(3)
    ]
    assert all(box is not None for box in boxes)
    heights = [b[3] - b[1] for b in boxes if b]
    tops = [b[1] for b in boxes if b]
    centres = [(b[0] + b[2]) // 2 for b in boxes if b]
    assert max(heights) - min(heights) <= 6
    assert max(tops) - min(tops) <= 6
    assert all(abs(c - PANEL_W // 2) <= 4 for c in centres)
    # Bust is the top half of the re-aligned sheet; asset stacks bust over sheet.
    assert Image.open(bust).size == (PANEL_W * 3, PANEL_H // 2)
    assert Image.open(asset).size == (PANEL_W * 3, PANEL_H + PANEL_H // 2)


def test_normalize_returns_false_when_width_not_divisible(tmp_path):
    fullbody, bust, asset = _paths(tmp_path)
    Image.new("RGB", (PANEL_W * 3 + 1, PANEL_H), BG).save(fullbody)
    Image.new("RGB", (PANEL_W * 3, PANEL_H // 2), BG).save(bust)
    Image.new("RGB", (PANEL_W * 3, PANEL_H + PANEL_H // 2), BG).save(asset)

    assert panel_align.normalize_turnaround(fullbody, bust, asset) is False


def test_normalize_skips_when_a_panel_has_no_subject(tmp_path):
    fullbody, bust, asset = _paths(tmp_path)
    sheet = _sheet([(100, 100, 200, 500), (100, 100, 200, 500), (0, 0, 0, 0)])
    sheet.save(fullbody)
    Image.new("RGB", (PANEL_W * 3, PANEL_H // 2), BG).save(bust)
    Image.new("RGB", (PANEL_W * 3, PANEL_H + PANEL_H // 2), BG).save(asset)

    assert panel_align.normalize_turnaround(fullbody, bust, asset) is False


def test_pipeline_aligns_only_quadrupeds(tmp_path, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        panel_align,
        "normalize_turnaround",
        lambda *a, **k: calls.append(a) or True,
    )
    saved = {
        "fullbody_threeview": tmp_path / "fb.png",
        "bust_threeview": tmp_path / "bust.png",
        "asset_sheet": tmp_path / "sheet.png",
    }
    pipe = ActorPipeline()

    human = create_job(
        pipeline_id="actor", asset_kind="actors", name="Human",
        params={"species": "human", "description": "one adult"},
    )
    pipe.postprocess_job_outputs(human, saved)
    assert calls == []

    quadruped = create_job(
        pipeline_id="actor", asset_kind="actors", name="Cat",
        params={"species": "quadruped", "description": "a tabby cat"},
    )
    pipe.postprocess_job_outputs(quadruped, saved)
    assert len(calls) == 1
