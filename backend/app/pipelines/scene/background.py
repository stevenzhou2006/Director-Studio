"""Detect backgroundless reference plates and cut generated angles out.

The multi-angle pipeline is sometimes used with an isolated subject (an actor
cutout on plain white or a transparent PNG) rather than a full set. Feeding that
plate to Qwen Image 2.1 without any hint makes the model invent a plausible
environment, so every angle comes back with a hallucinated background.

If the reference has no background, the pipeline forces an isolated white
backdrop in the prompt and then knocks that backdrop out of every output so the
whole angle set stays transparent, matching the source.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

logger = logging.getLogger("director_studio.scene.background")

# A border is "flat white" when every sampled pixel is at least this bright and
# the channel spread across the border stays within ``_FLAT_SPREAD``.
_WHITE_FLOOR = 235
_FLAT_SPREAD = 28
_MIN_WHITE_FRACTION = 0.85
# Overall alpha fraction that marks a plate as already transparent.
_TRANSPARENT_FRACTION = 0.05
# 1-norm distance from the sampled background colour still treated as backdrop.
_FILL_TOLERANCE = 48
# Magenta never survives a white-backdrop cut and is easy to detect afterwards.
_SENTINEL = (255, 0, 255)


def _border_samples(img: Image.Image) -> list[tuple[int, int, int, int]]:
    rgba = img.convert("RGBA")
    w, h = rgba.size
    if w < 2 or h < 2:
        return []
    step = max(1, min(w, h) // 200)
    px = rgba.load()
    assert px is not None
    points: list[tuple[int, int]] = []
    for x in range(0, w, step):
        points.append((x, 0))
        points.append((x, h - 1))
    for y in range(0, h, step):
        points.append((0, y))
        points.append((w - 1, y))
    return [px[x, y] for x, y in points]


def _white_backdrop(img: Image.Image) -> tuple[int, int, int] | None:
    """Average colour of a flat near-white border, or None if there is none."""
    samples = [s for s in _border_samples(img) if s[3] >= 16]
    if not samples:
        return None
    whites = [s for s in samples if min(s[:3]) >= _WHITE_FLOOR]
    if len(whites) / len(samples) < _MIN_WHITE_FRACTION:
        return None
    for channel in range(3):
        values = [s[channel] for s in whites]
        if max(values) - min(values) > _FLAT_SPREAD:
            return None
    return (
        sum(s[0] for s in whites) // len(whites),
        sum(s[1] for s in whites) // len(whites),
        sum(s[2] for s in whites) // len(whites),
    )


def has_no_background(image_path: Path) -> bool:
    """True when the plate is a transparent or flat-white isolated subject."""
    try:
        with Image.open(image_path) as img:
            rgba = img.convert("RGBA")
    except (OSError, ValueError):
        logger.warning("background probe failed for %s", image_path, exc_info=True)
        return False

    alpha = rgba.getchannel("A")
    total = rgba.width * rgba.height
    if total and sum(alpha.histogram()[:16]) / total >= _TRANSPARENT_FRACTION:
        return True
    return _white_backdrop(rgba) is not None


def _already_cut_out(img: Image.Image) -> bool:
    alpha = img.convert("RGBA").getchannel("A")
    total = img.width * img.height
    return bool(total) and sum(alpha.histogram()[:16]) / total >= _TRANSPARENT_FRACTION


def cut_out_background(image_path: Path) -> bool:
    """Knock a flat light backdrop out of one generated plate, in place.

    Connectivity is preserved with a border flood fill, so white areas inside the
    subject (fur, shirts, highlight) stay opaque. Returns True when the file was
    rewritten with an alpha channel.
    """
    try:
        with Image.open(image_path) as img:
            rgba = img.convert("RGBA")
    except (OSError, ValueError):
        logger.warning("background cutout failed to open %s", image_path, exc_info=True)
        return False

    if _already_cut_out(rgba):
        return False

    backdrop = _white_backdrop(rgba)
    if backdrop is None:
        # The model did not honour the isolated prompt; leave it untouched.
        return False

    work = rgba.convert("RGB")
    w, h = work.size
    step = max(1, min(w, h) // 100)
    seeds: list[tuple[int, int]] = []
    for x in range(0, w, step):
        seeds.append((x, 0))
        seeds.append((x, h - 1))
    for y in range(0, h, step):
        seeds.append((0, y))
        seeds.append((w - 1, y))
    px = work.load()
    assert px is not None
    for x, y in seeds:
        if min(px[x, y]) < _WHITE_FLOOR:
            continue
        ImageDraw.floodfill(work, (x, y), _SENTINEL, thresh=_FILL_TOLERANCE)

    sentinel_layer = Image.new("RGB", (w, h), _SENTINEL)
    backdrop_mask = ImageChops.difference(work, sentinel_layer).convert("L")
    backdrop_mask = backdrop_mask.point(lambda v: 255 if v == 0 else 0, mode="L")
    foreground = ImageOps.invert(backdrop_mask)
    # Pull the matte in one pixel to drop the anti-aliased white fringe, then
    # soften the edge so the cutout composites cleanly.
    foreground = foreground.filter(ImageFilter.MinFilter(3))
    foreground = foreground.filter(ImageFilter.GaussianBlur(0.7))

    rgba.putalpha(foreground)
    try:
        rgba.save(image_path, format="PNG", optimize=True)
    except OSError:
        logger.warning("background cutout failed to save %s", image_path, exc_info=True)
        return False
    return True
