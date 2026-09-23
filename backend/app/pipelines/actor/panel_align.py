"""Deterministic alignment of the actor turnaround sheet.

The image model does not keep a consistent subject scale or ground line across
the three panels of a turnaround. A quadruped's ``fullbody_threeview`` therefore
comes back with each view at a different height and vertical position, and the
``bust_threeview`` (a top-of-sheet crop) inherits the same drift.

This module re-frames every equal panel to a common subject height, horizontal
centre, and baseline, then rebuilds the full-body sheet, the derived bust crop,
and the stacked asset sheet in place. It only touches geometry — pixels come
from the generated panels, so no subject detail is invented.
"""

from __future__ import annotations

import logging
import statistics
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

logger = logging.getLogger("director_studio.actor.panel_align")

PANELS = 3
# Studio backdrop fill used behind each re-framed panel.
FILL = (233, 234, 235)
# Fraction of panel height the tallest subject may occupy, and the baseline.
_MAX_SUBJECT_FRAC = 0.84
_BASELINE_FRAC = 0.90
# Luminance/saturation thresholds that separate the solid subject from the set.
_SUBJECT_LUM = 178
_SUBJECT_SAT = 45
_MASK_MARGIN = 14


def _row_background(panel: Image.Image, margin: int = _MASK_MARGIN) -> Image.Image:
    """Per-row backdrop luminance from the panel's clean left/right margins."""
    w, h = panel.size
    px = panel.load()
    assert px is not None
    column = Image.new("L", (1, h))
    cp = column.load()
    assert cp is not None
    xs = list(range(margin, margin + 20, 3)) + list(
        range(w - 1 - margin - 16, w - margin, 3)
    )
    last = 210
    for y in range(h):
        values: list[float] = []
        for x in xs:
            r, g, b = px[x, y]
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if 150 < lum < 250 and max(r, g, b) - min(r, g, b) < 20:
                values.append(lum)
        if values:
            last = statistics.median(values)
        cp[0, y] = round(last)
    return column.resize((w, h))


def _saturation(panel: Image.Image) -> Image.Image:
    r, g, b = panel.split()
    return ImageChops.difference(
        ImageChops.lighter(ImageChops.lighter(r, g), b),
        ImageChops.darker(ImageChops.darker(r, g), b),
    )


def _strict_mask(panel: Image.Image) -> Image.Image:
    """Solid subject silhouette: dark or colourful pixels."""
    lum = panel.convert("L").point(lambda v: 255 if v < _SUBJECT_LUM else 0)
    sat = _saturation(panel).point(lambda v: 255 if v > _SUBJECT_SAT else 0)
    return ImageChops.lighter(lum, sat)


def _loose_mask(panel: Image.Image, margin: int = _MASK_MARGIN) -> Image.Image:
    """Subject plus soft edges/shadow, measured against the smooth backdrop."""
    diff = ImageChops.difference(panel.convert("L"), _row_background(panel, margin))
    lum = diff.point(lambda v: 255 if v > 14 else 0)
    sat = _saturation(panel).point(lambda v: 255 if v > 30 else 0)
    return ImageChops.lighter(lum, sat)


def _subject_bbox(mask: Image.Image) -> tuple[int, int, int, int] | None:
    """Projection bbox that ignores thin stray marks and separator slivers."""
    w, h = mask.size
    small = (
        mask.resize((max(1, w // 4), max(1, h // 4)), Image.Resampling.BILINEAR)
        .point(lambda v: 255 if v > 40 else 0)
    )
    sw, sh = small.size
    px = small.load()
    assert px is not None
    cols = [0] * sw
    rows = [0] * sh
    for y in range(2, sh - 2):
        for x in range(2, sw - 2):
            if px[x, y]:
                cols[x] += 1
                rows[y] += 1
    xs = [x for x in range(sw) if cols[x] > 0.02 * sh]
    ys = [y for y in range(sh) if rows[y] > 0.012 * sw]
    if not xs or not ys:
        return None
    return (min(xs) * 4, min(ys) * 4, (max(xs) + 1) * 4, (max(ys) + 1) * 4)


def _aligned_panel(panel: Image.Image, target_h: int, top: int) -> Image.Image | None:
    bbox = _subject_bbox(_strict_mask(panel))
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    subject_h = y1 - y0
    if subject_h < panel.height * 0.25:
        return None
    subject = panel.crop((x0, y0, x1, y1))
    mask = _loose_mask(panel).crop((x0, y0, x1, y1))
    scale = target_h / subject_h
    width = max(1, int(subject.width * scale))
    subject = subject.resize((width, target_h), Image.Resampling.LANCZOS)
    mask = mask.resize((width, target_h), Image.Resampling.LANCZOS)
    mask = mask.filter(ImageFilter.GaussianBlur(1.0))
    canvas = Image.new("RGB", panel.size, FILL)
    canvas.paste(subject, ((panel.width - width) // 2, top), mask)
    return canvas


def normalize_turnaround(
    fullbody_path: Path,
    bust_path: Path,
    asset_sheet_path: Path,
    *,
    panels: int = PANELS,
) -> bool:
    """Re-align a ``panels``-up turnaround and its bust/asset derivatives.

    Returns True when the sheet was rewritten. Any panel that cannot be measured
    is left untouched, and the whole operation is skipped rather than risk a
    degenerate layout.
    """
    try:
        source = Image.open(fullbody_path).convert("RGB")
    except (OSError, ValueError):
        logger.warning("turnaround alignment could not open %s", fullbody_path, exc_info=True)
        return False

    width, height = source.size
    if panels < 2 or width % panels != 0:
        return False
    panel_w = width // panels
    if panel_w < 200 or height < 200:
        return False

    slices = [
        source.crop((i * panel_w, 0, (i + 1) * panel_w, height)) for i in range(panels)
    ]
    bboxes = [_subject_bbox(_strict_mask(panel)) for panel in slices]
    if any(bbox is None for bbox in bboxes):
        logger.info("turnaround alignment skipped: a panel has no measurable subject")
        return False
    heights = [bbox[3] - bbox[1] for bbox in bboxes if bbox is not None]
    for bbox, subject_h in zip(bboxes, heights):
        if bbox is None or subject_h < height * 0.25:
            return False
    target_h = min(max(heights), int(height * _MAX_SUBJECT_FRAC))
    top = int(height * _BASELINE_FRAC) - target_h

    rebuilt: list[Image.Image] = []
    for panel in slices:
        aligned = _aligned_panel(panel, target_h, top)
        if aligned is None:
            return False
        rebuilt.append(aligned)

    sheet = Image.new("RGB", source.size, FILL)
    for i, panel in enumerate(rebuilt):
        sheet.paste(panel, (i * panel_w, 0))

    try:
        sheet.save(fullbody_path, format="PNG")
        bust = sheet.crop((0, 0, width, height // 2))
        bust.save(bust_path, format="PNG")
        asset = Image.new("RGB", (width, bust.height + height), FILL)
        asset.paste(bust, (0, 0))
        asset.paste(sheet, (0, bust.height))
        asset.save(asset_sheet_path, format="PNG")
    except OSError:
        logger.warning("turnaround alignment failed to save", exc_info=True)
        return False
    return True
