"""Vertical calligraphy poem overlay renderer.

Renders a title card (《title》 in Ma Shan Zheng calligraphy + ``dynasty · author``
in Noto Serif + a thin rule and a red seal) and the poem lines as traditional
vertical columns (read top-down, columns right-to-left). Each column fades in
when its line starts and stays on screen until the end; the last column carries
a small red seal.

Ported from the cat_poet series ``poem_overlay.py`` (v2 delivery standard) and
generalised so the geometry scales from the 576x1024 reference design.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_REF_HEIGHT = 1024
_REF_WIDTH = 576

INK = (43, 38, 32, 255)
HALO = (250, 248, 243, 150)
SEAL_RED = (168, 42, 32, 235)
RULE = (120, 100, 70, 160)

_ASSETS_DIR = Path(__file__).with_name("assets")
_VENDORED_CALLIGRAPHY = _ASSETS_DIR / "mashanzheng.ttf"
_DEFAULT_SERIF_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSerifCJK-Bold.ttc",
)


class PoemOverlayError(ValueError):
    """Raised when the overlay cannot be rendered."""


def _require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise PoemOverlayError(f"{name} is required to render the poem overlay")
    return resolved


def _first_existing(paths: list[str | None]) -> str | None:
    for candidate in paths:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def resolve_fonts(
    *,
    calligraphy_font: str | None = None,
    serif_font: str | None = None,
) -> tuple[str, str]:
    """Resolve usable calligraphy and serif font paths, or raise clearly."""
    calligraphy = _first_existing(
        [
            calligraphy_font,
            os.environ.get("DS_POEM_CALLIGRAPHY_FONT"),
            str(_VENDORED_CALLIGRAPHY),
        ]
    )
    serif = _first_existing(
        [
            serif_font,
            os.environ.get("DS_POEM_SERIF_FONT"),
            *_DEFAULT_SERIF_CANDIDATES,
            calligraphy,
        ]
    )
    if calligraphy is None:
        raise PoemOverlayError(
            "no calligraphy font found; provide calligraphy_font or set "
            "DS_POEM_CALLIGRAPHY_FONT"
        )
    if serif is None:
        raise PoemOverlayError(
            "no serif CJK font found; provide serif_font or set DS_POEM_SERIF_FONT"
        )
    return calligraphy, serif


def _probe_video(path: Path) -> tuple[int, int, float, bool]:
    ffprobe = _require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise PoemOverlayError(f"unable to probe video: {path}")
    try:
        width_text, height_text = result.stdout.strip().split("x")
        width, height = int(width_text), int(height_text)
    except ValueError as exc:
        raise PoemOverlayError(f"unexpected video dimensions: {result.stdout!r}") from exc

    duration_result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        duration = float(duration_result.stdout.strip())
    except (TypeError, ValueError):
        duration = 0.0

    audio_result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    has_audio = bool(audio_result.stdout.strip())
    return width, height, duration, has_audio


def _halo_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill=INK,
    halo=HALO,
    radius: int = 2,
) -> None:
    x, y = xy
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx or dy:
                draw.text((x + dx, y + dy), text, font=font, fill=halo)
    draw.text((x, y), text, font=font, fill=fill)


def _build_title_card(
    *,
    title: str,
    author: str,
    dynasty: str,
    seal_text: str,
    calligraphy: str,
    serif: str,
    scale: float,
    work_dir: Path,
) -> Path:
    font_title = ImageFont.truetype(calligraphy, max(1, round(72 * scale)))
    font_author = ImageFont.truetype(serif, max(1, round(26 * scale)))
    font_seal = ImageFont.truetype(calligraphy, max(1, round(22 * scale)))

    card = Image.new(
        "RGBA",
        (max(1, round(360 * scale)), max(1, round(160 * scale))),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(card)
    title_text = f"《{title}》"
    box = draw.textbbox((0, 0), title_text, font=font_title)
    title_width = box[2] - box[0]
    _halo_text(draw, (10 - box[0], 0), title_text, font_title)

    author_text = f"{dynasty} · {author}"
    author_box = draw.textbbox((0, 0), author_text, font=font_author)
    author_y = round(88 * scale)
    _halo_text(draw, (14, author_y), author_text, font_author)
    author_height = author_box[3] - author_box[1]
    rule_width = max(title_width, author_box[2] - author_box[0]) * 0.62
    draw.rectangle(
        [
            14,
            author_y + author_height + 12,
            14 + rule_width,
            author_y + author_height + 14,
        ],
        fill=RULE,
    )
    seal_x = 14 + rule_width + 10
    seal_size = max(1, round(30 * scale))
    draw.rounded_rectangle(
        [seal_x, author_y + 2, seal_x + seal_size, author_y + 2 + seal_size],
        radius=max(1, round(4 * scale)),
        outline=SEAL_RED,
        width=max(1, round(2 * scale)),
    )
    seal_box = draw.textbbox((0, 0), seal_text, font=font_seal)
    draw.text(
        (
            seal_x + seal_size / 2 - (seal_box[2] - seal_box[0]) / 2 - seal_box[0],
            author_y + 2 + seal_size / 2 - (seal_box[3] - seal_box[1]) / 2 - seal_box[1],
        ),
        seal_text,
        font=font_seal,
        fill=SEAL_RED,
    )
    path = work_dir / "title.png"
    card.save(path)
    return path


def _build_column(
    text: str,
    *,
    calligraphy: str,
    scale: float,
    cell: int,
    work_dir: Path,
    index: int,
) -> tuple[Path, int]:
    font = ImageFont.truetype(calligraphy, max(1, round(46 * scale)))
    column_width = max(1, round(84 * scale))
    image = Image.new(
        "RGBA",
        (column_width, len(text) * cell + max(1, round(24 * scale))),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(image)
    for position, char in enumerate(text):
        box = draw.textbbox((0, 0), char, font=font)
        char_width = box[2] - box[0]
        _halo_text(
            draw,
            ((image.width - char_width) / 2 - box[0], round(12 * scale) + position * cell),
            char,
            font,
        )
    path = work_dir / f"col{index}.png"
    image.save(path)
    return path, image.height


def _build_seal(
    *,
    seal_text: str,
    calligraphy: str,
    scale: float,
    work_dir: Path,
) -> Path:
    font = ImageFont.truetype(calligraphy, max(1, round(30 * scale)))
    image = Image.new(
        "RGBA",
        (max(1, round(84 * scale)), max(1, round(60 * scale))),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(image)
    seal_size = max(1, round(30 * scale))
    left = max(1, round(27 * scale))
    top = max(1, round(8 * scale))
    draw.rounded_rectangle(
        [left, top, left + seal_size, top + seal_size],
        radius=max(1, round(5 * scale)),
        outline=SEAL_RED,
        width=max(1, round(2 * scale)),
    )
    box = draw.textbbox((0, 0), seal_text, font=font)
    draw.text(
        (
            left + seal_size / 2 - (box[2] - box[0]) / 2 - box[0],
            top + seal_size / 2 - (box[3] - box[1]) / 2 - box[1],
        ),
        seal_text,
        font=font,
        fill=SEAL_RED,
    )
    path = work_dir / "seal.png"
    image.save(path)
    return path


def render_poem_overlay(
    *,
    input_path: Path,
    output_path: Path,
    title: str,
    author: str,
    lines: list[tuple[str, float]],
    dynasty: str = "唐",
    seal_text: str = "狸",
    width: int | None = None,
    height: int | None = None,
    calligraphy_font: str | None = None,
    serif_font: str | None = None,
    work_dir: Path | None = None,
) -> dict[str, float | int]:
    """Render the title card and vertical poem columns onto ``input_path``.

    ``lines`` is an ordered list of ``(text, start_seconds)``. Returns render
    metadata (duration, column count, resolved dimensions).
    """
    clean_title = str(title or "").strip()
    clean_author = str(author or "").strip()
    if not clean_title or not clean_author:
        raise PoemOverlayError("title and author are required")
    clean_lines = [
        (str(text).strip(), float(start))
        for text, start in lines
        if str(text).strip()
    ]
    if not clean_lines:
        raise PoemOverlayError("at least one poem line is required")

    input_path = Path(input_path)
    if not input_path.is_file():
        raise PoemOverlayError(f"input video not found: {input_path}")

    probe_width, probe_height, duration, has_audio = _probe_video(input_path)
    canvas_width = int(width) if width else probe_width
    canvas_height = int(height) if height else probe_height
    if canvas_width <= 0 or canvas_height <= 0:
        raise PoemOverlayError("video dimensions must be positive")

    scale = canvas_height / _REF_HEIGHT
    cell = max(1, round(54 * scale))
    calligraphy, serif = resolve_fonts(
        calligraphy_font=calligraphy_font,
        serif_font=serif_font,
    )

    import tempfile

    temp_root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="poem-overlay-"))
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        title_png = _build_title_card(
            title=clean_title,
            author=clean_author,
            dynasty=str(dynasty or "唐"),
            seal_text=seal_text or "狸",
            calligraphy=calligraphy,
            serif=serif,
            scale=scale,
            work_dir=temp_root,
        )
        column_paths: list[Path] = []
        for position, (text, _start) in enumerate(clean_lines):
            column_path, _ = _build_column(
                text,
                calligraphy=calligraphy,
                scale=scale,
                cell=cell,
                work_dir=temp_root,
                index=position,
            )
            column_paths.append(column_path)
        seal_path = _build_seal(
            seal_text=seal_text or "狸",
            calligraphy=calligraphy,
            scale=scale,
            work_dir=temp_root,
        )

        title_in, title_out = 2.0, min(6.0, max(3.0, duration - 3.0))
        title_x = round(36 * scale)
        title_y = round(84 * scale)
        top_y = round(60 * scale)
        step = round(66 * scale)
        start_x = canvas_width - round(96 * scale)

        inputs = [
            "-i",
            str(input_path),
            "-framerate",
            "24",
            "-loop",
            "1",
            "-i",
            str(title_png),
        ]
        title_filter = (
            f"[1:v]format=rgba,fade=t=in:st={title_in}:d=0.8:alpha=1,"
            f"fade=t=out:st={title_out}:d=0.8:alpha=1[ttl];"
            f"[0:v][ttl]overlay={title_x}:{title_y}:"
            f"enable='between(t,{title_in - 0.01},{title_out + 0.81})'[cv0]"
        )
        parts = [title_filter]
        previous = "cv0"
        column_x = start_x
        column_heights: list[int] = []
        for position, (text, start) in enumerate(clean_lines):
            input_index = position + 2
            fade_out = max(duration - 1.2, start + 1.0) if duration else start + 1.0
            inputs += [
                "-framerate",
                "24",
                "-loop",
                "1",
                "-i",
                str(column_paths[position]),
            ]
            parts.append(
                f"[{input_index}:v]format=rgba,fade=t=in:st={start:.2f}:d=0.6:alpha=1,"
                f"fade=t=out:st={fade_out:.2f}:d=0.8:alpha=1[c{position}];"
                f"[{previous}][c{position}]overlay={column_x}:{top_y}:"
                f"enable='between(t,{start - 0.01:.2f},{fade_out + 0.81:.2f})'"
                f"[cv{position + 1}]"
            )
            previous = f"cv{position + 1}"
            column_x -= step
            column_heights.append(len(text) * cell + round(24 * scale))

        last_start = clean_lines[-1][1]
        last_end = last_start + 2.2
        seal_input_index = len(clean_lines) + 2
        inputs += [
            "-framerate",
            "24",
            "-loop",
            "1",
            "-i",
            str(seal_path),
        ]
        seal_fade_out = max(duration - 1.2, last_end + 0.8) if duration else last_end + 0.8
        seal_y = top_y + column_heights[-1] + round(6 * scale)
        parts.append(
            f"[{seal_input_index}:v]format=rgba,fade=t=in:st={last_end:.2f}:d=0.6:alpha=1,"
            f"fade=t=out:st={seal_fade_out:.2f}:d=0.8:alpha=1[sl];"
            f"[{previous}][sl]overlay={column_x + step}:{seal_y}:"
            f"enable='between(t,{last_end - 0.01:.2f},{seal_fade_out + 0.81:.2f})'[vout]"
        )

        filter_complex = ";".join(parts)
        command = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", filter_complex]
        command += ["-map", "[vout]"]
        if has_audio:
            command += ["-map", "0:a", "-c:a", "copy"]
        command += [
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise PoemOverlayError(
                f"ffmpeg overlay failed: {result.stderr.strip()[-800:]}"
            )
    finally:
        if work_dir is None:
            shutil.rmtree(temp_root, ignore_errors=True)

    return {
        "duration_s": duration,
        "line_count": len(clean_lines),
        "width": canvas_width,
        "height": canvas_height,
    }
