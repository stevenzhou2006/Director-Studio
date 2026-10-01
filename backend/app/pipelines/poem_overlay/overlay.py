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
from typing import Any

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


def render_poem_title_still(
    *,
    input_path: Path,
    output_path: Path,
    title: str,
    author: str,
    dynasty: str = "唐",
    seal_text: str = "狸",
    calligraphy_font: str | None = None,
    serif_font: str | None = None,
    work_dir: Path | None = None,
    margin_x: int | None = None,
    margin_y: int | None = None,
    columns: list[str] | None = None,
) -> dict[str, int]:
    """Composite the title card (and optional poem columns) onto a still frame.

    Places ``《title》`` + ``dynasty · author`` + rule + red seal in the upper-left
    of ``input_path``. When ``columns`` is provided, each line is also rendered as
    a traditional vertical column on the right side (read top-down, columns
    right-to-left), matching the video overlay geometry — so a title-plus-first-line
    shot shows its opening line on the still too. Writes ``output_path``. The
    model-rendered plate stays text-free; all text is font-composited here.
    """
    clean_title = str(title or "").strip()
    clean_author = str(author or "").strip()
    if not clean_title or not clean_author:
        raise PoemOverlayError("title and author are required")

    input_path = Path(input_path)
    if not input_path.is_file():
        raise PoemOverlayError(f"input image not found: {input_path}")

    calligraphy, serif = resolve_fonts(
        calligraphy_font=calligraphy_font,
        serif_font=serif_font,
    )

    import tempfile

    temp_root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="poem-still-"))
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        base = Image.open(input_path).convert("RGBA")
        width, height = base.size
        if width <= 0 or height <= 0:
            raise PoemOverlayError("image dimensions must be positive")
        scale = height / _REF_HEIGHT
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
        card = Image.open(title_png).convert("RGBA")
        pos_x = int(margin_x) if margin_x is not None else round(36 * scale)
        pos_y = int(margin_y) if margin_y is not None else round(84 * scale)
        base.alpha_composite(card, (pos_x, pos_y))

        clean_columns = [str(c).strip() for c in (columns or []) if str(c).strip()]
        if clean_columns:
            cell = max(1, round(54 * scale))
            top_y = round(60 * scale)
            step = round(66 * scale)
            column_x = width - round(96 * scale)
            for index, text in enumerate(clean_columns):
                column_png, _ = _build_column(
                    text,
                    calligraphy=calligraphy,
                    scale=scale,
                    cell=cell,
                    work_dir=temp_root,
                    index=index,
                )
                column_img = Image.open(column_png).convert("RGBA")
                base.alpha_composite(column_img, (column_x, top_y))
                column_x -= step

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        base.save(output_path)
    finally:
        if work_dir is None:
            shutil.rmtree(temp_root, ignore_errors=True)

    return {"width": width, "height": height}


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
    replacement_audio: Path | None = None,
    show_title: bool = True,
) -> dict[str, float | int | bool]:
    """Render the title card and vertical poem columns onto ``input_path``.

    ``lines`` is an ordered list of ``(text, start_seconds)``. Returns render
    metadata (duration, column count, resolved dimensions).

    ``show_title`` gates the ``《title》 dynasty · author`` card. Per-shot
    finalize keeps it ``False`` for every shot except the first, so the card
    appears exactly once in the concatenated film while each shot still gets
    its own subtitle column and seal.

    When ``replacement_audio`` is given, the source video's audio track is
    discarded and this exact recording is muxed in instead (padded with silence
    to the video length). Without it the source audio is copied through
    unchanged, so H3's natively generated audio is preserved.
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
    if replacement_audio is not None and not Path(replacement_audio).is_file():
        raise PoemOverlayError(
            f"replacement audio not found: {replacement_audio}"
        )

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

        top_y = round(60 * scale)
        step = round(66 * scale)
        start_x = canvas_width - round(96 * scale)

        inputs = ["-i", str(input_path)]
        parts: list[str] = []
        previous = "0:v"
        if show_title:
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
            title_in, title_out = 2.0, min(6.0, max(3.0, duration - 3.0))
            title_x = round(36 * scale)
            title_y = round(84 * scale)
            inputs += [
                "-framerate",
                "24",
                "-loop",
                "1",
                "-i",
                str(title_png),
            ]
            parts.append(
                f"[1:v]format=rgba,fade=t=in:st={title_in}:d=0.8:alpha=1,"
                f"fade=t=out:st={title_out}:d=0.8:alpha=1[ttl];"
                f"[0:v][ttl]overlay={title_x}:{title_y}:"
                f"enable='between(t,{title_in - 0.01},{title_out + 0.81})'[cv0]"
            )
            previous = "cv0"
        base_input = 2 if show_title else 1
        column_x = start_x
        column_heights: list[int] = []
        for position, (text, start) in enumerate(clean_lines):
            input_index = position + base_input
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
        seal_input_index = len(clean_lines) + base_input
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

        audio_input_index: int | None = None
        if replacement_audio is not None:
            # Inputs: 0=source video, [1=title when shown],
            # columns, then seal; audio follows the seal.
            audio_input_index = len(clean_lines) + base_input + 1
            inputs = [*inputs, "-i", str(replacement_audio)]
            # Pad to a finite length: an infinite apad combined with the
            # looped-PNG overlay graph never lets -shortest terminate.
            pad_to = duration if duration > 0 else 3600.0
            parts.append(f"[{audio_input_index}:a:0]apad=whole_dur={pad_to}[arep]")

        filter_complex = ";".join(parts)
        command = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", filter_complex]
        command += ["-map", "[vout]"]
        if audio_input_index is not None:
            command += ["-map", "[arep]", "-c:a", "aac", "-b:a", "192k"]
        elif has_audio:
            command += ["-map", "0:a", "-c:a", "copy"]
        # Hard output-duration cap. ffmpeg 6.x never lets -shortest terminate a
        # graph that mixes -loop 1 stills with apad, so bound the mux explicitly.
        if duration > 0:
            command += ["-t", f"{duration:.3f}"]
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
        encode_timeout = max(300.0, duration * 60.0)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=encode_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise PoemOverlayError(
                f"ffmpeg overlay timed out after {encode_timeout:.0f}s"
            ) from exc
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
        "audio_replaced": replacement_audio is not None,
        "title_shown": bool(show_title),
    }


def render_master_overlay(
    *,
    input_path: Path,
    output_path: Path,
    title: str,
    author: str,
    segments: list[dict[str, Any]],
    recitation_audio: Path | None = None,
    watermark: str = "",
    dynasty: str = "唐",
    seal_text: str = "狸",
    width: int | None = None,
    height: int | None = None,
    calligraphy_font: str | None = None,
    serif_font: str | None = None,
    work_dir: Path | None = None,
    show_title: bool = True,
) -> dict[str, Any]:
    """Finish a concatenated master film in one pass.

    ``segments`` is an ordered list, one per shot, each carrying an absolute
    ``offset_s`` on the master timeline and that shot's ``lines`` as
    ``(text, local_start_s)`` pairs. Global line start = ``offset_s +
    local_start_s``. The title card is composited exactly once at the head of
    the film; every poem column fades in on the master timeline and stays to
    the end (columns accumulate right-to-left); the last column carries the
    red seal. When ``recitation_audio`` is given it replaces the whole film's
    audio track (padded with silence to the master length). When ``watermark``
    is non-empty it is burned into the bottom-right corner across the entire
    film. All text is font-composited here; the model-rendered plate stays
    text-free.
    """
    clean_title = str(title or "").strip()
    clean_author = str(author or "").strip()
    if not clean_title or not clean_author:
        raise PoemOverlayError("title and author are required")
    if not segments:
        raise PoemOverlayError("at least one segment is required")

    input_path = Path(input_path)
    if not input_path.is_file():
        raise PoemOverlayError(f"input video not found: {input_path}")
    if recitation_audio is not None and not Path(recitation_audio).is_file():
        raise PoemOverlayError(f"recitation audio not found: {recitation_audio}")

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

    # Normalise segments into (offset_s, [(text, global_start_s), ...]).
    timed_segments: list[tuple[float, list[tuple[str, float]]]] = []
    for seg in segments:
        offset = float(seg.get("offset_s") or 0.0)
        raw_lines = seg.get("lines") or []
        lines: list[tuple[str, float]] = []
        for entry in raw_lines:
            if isinstance(entry, dict):
                text = str(entry.get("text") or "").strip()
                start = float(entry.get("start_s") or 0.0)
            else:
                text = str(entry[0]).strip()
                start = float(entry[1])
            if text:
                lines.append((text, offset + start))
        if lines:
            timed_segments.append((offset, lines))
    if not timed_segments:
        raise PoemOverlayError("no poem lines to overlay across segments")

    import tempfile

    temp_root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="poem-master-"))
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        inputs = ["-i", str(input_path)]
        parts: list[str] = []
        previous = "0:v"
        next_input = 1

        if show_title:
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
            title_in = 0.5
            title_out = min(5.0, max(3.0, duration - 3.0)) if duration > 0 else 5.0
            title_x = round(36 * scale)
            title_y = round(84 * scale)
            inputs += ["-framerate", "24", "-loop", "1", "-i", str(title_png)]
            parts.append(
                f"[{next_input}:v]format=rgba,"
                f"fade=t=in:st={title_in}:d=0.8:alpha=1,"
                f"fade=t=out:st={title_out}:d=0.8:alpha=1[ttl];"
                f"[0:v][ttl]overlay={title_x}:{title_y}:"
                f"enable='between(t,{title_in - 0.01},{title_out + 0.81})'[cv0]"
            )
            previous = "cv0"
            next_input += 1

        top_y = round(60 * scale)
        step = round(66 * scale)
        start_x = canvas_width - round(96 * scale)

        # Build every column image first so the overlay loop stays simple.
        col_paths: dict[tuple[int, int], Path] = {}
        for seg_index, (_offset, lines) in enumerate(timed_segments):
            for line_index, (text, _gstart) in enumerate(lines):
                col_path, _ = _build_column(
                    text,
                    calligraphy=calligraphy,
                    scale=scale,
                    cell=cell,
                    work_dir=temp_root,
                    index=seg_index * 100 + line_index,
                )
                col_paths[(seg_index, line_index)] = col_path

        # Per-segment time windows: each segment's columns and seal are visible
        # only during [offset, segment_end) so a later segment can never overlap
        # an earlier one. segment_end = next segment's offset (film end for the
        # last). Columns lay out right-to-left within each segment.
        seg_ends: list[float] = []
        for i, (offset, _lines) in enumerate(timed_segments):
            if i + 1 < len(timed_segments):
                seg_ends.append(timed_segments[i + 1][0])
            elif duration > 0:
                seg_ends.append(duration)
            else:
                seg_ends.append(offset + 3.0)

        overlay_index = 0
        for seg_index, (_offset, lines) in enumerate(timed_segments):
            seg_end = seg_ends[seg_index]
            column_x = start_x
            for line_index, (text, gstart) in enumerate(lines):
                col_path = col_paths[(seg_index, line_index)]
                fade_out = max(gstart + 1.0, seg_end - 0.4)
                inputs += ["-framerate", "24", "-loop", "1", "-i", str(col_path)]
                parts.append(
                    f"[{next_input}:v]format=rgba,"
                    f"fade=t=in:st={gstart:.2f}:d=0.6:alpha=1,"
                    f"fade=t=out:st={fade_out:.2f}:d=0.8:alpha=1[c{overlay_index}];"
                    f"[{previous}][c{overlay_index}]overlay={column_x}:{top_y}:"
                    f"enable='between(t,{gstart - 0.01:.2f},{fade_out + 0.81:.2f})'"
                    f"[cv{overlay_index + 1}]"
                )
                previous = f"cv{overlay_index + 1}"
                next_input += 1
                overlay_index += 1
                column_x -= step

            # This segment's seal, under its last column, visible to seg_end.
            last_gstart = lines[-1][1]
            seal_in = last_gstart + 2.2
            if seal_in < seg_end - 0.2:
                seal_path = _build_seal(
                    seal_text=seal_text or "狸",
                    calligraphy=calligraphy,
                    scale=scale,
                    work_dir=temp_root,
                )
                seal_fade_out = max(seal_in + 0.8, seg_end - 0.2)
                last_col_x = column_x + step
                last_col_height = len(lines[-1][0]) * cell + round(24 * scale)
                seal_y = top_y + last_col_height + round(6 * scale)
                inputs += ["-framerate", "24", "-loop", "1", "-i", str(seal_path)]
                parts.append(
                    f"[{next_input}:v]format=rgba,"
                    f"fade=t=in:st={seal_in:.2f}:d=0.6:alpha=1,"
                    f"fade=t=out:st={seal_fade_out:.2f}:d=0.8:alpha=1[sl{overlay_index}];"
                    f"[{previous}][sl{overlay_index}]overlay={last_col_x}:{seal_y}:"
                    f"enable='between(t,{seal_in - 0.01:.2f},{seal_fade_out + 0.81:.2f})'"
                    f"[cv{overlay_index + 1}]"
                )
                previous = f"cv{overlay_index + 1}"
                next_input += 1
                overlay_index += 1

        # Watermark burned across the whole film, bottom-right.
        clean_watermark = str(watermark or "").strip()
        if clean_watermark:
            wm_file = temp_root / "watermark.txt"
            wm_file.write_text(clean_watermark, encoding="utf-8")
            wm_size = max(1, round(46 * scale))
            margin = max(1, round(34 * scale))
            parts.append(
                f"[{previous}]drawtext=fontfile={serif}:textfile={wm_file}:"
                f"fontsize={wm_size}:fontcolor=0x2b2620@0.85:borderw=2:"
                f"bordercolor=0xfaf8f3@0.55:"
                f"x=w-text_w-{margin}:y=h-text_h-{margin}[vw]"
            )
            previous = "vw"

        # Audio: unified recitation replaces the whole track when provided.
        audio_input_index: int | None = None
        if recitation_audio is not None:
            audio_input_index = next_input
            inputs += ["-i", str(recitation_audio)]
            pad_to = duration if duration > 0 else 3600.0
            parts.append(
                f"[{audio_input_index}:a:0]apad=whole_dur={pad_to}[arep]"
            )

        filter_complex = ";".join(parts)
        command = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", filter_complex]
        command += ["-map", f"[{previous}]"]
        if audio_input_index is not None:
            command += ["-map", "[arep]", "-c:a", "aac", "-b:a", "192k"]
        elif has_audio:
            command += ["-map", "0:a", "-c:a", "copy"]
        if duration > 0:
            command += ["-t", f"{duration:.3f}"]
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
        encode_timeout = max(300.0, duration * 60.0)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=encode_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise PoemOverlayError(
                f"ffmpeg master overlay timed out after {encode_timeout:.0f}s"
            ) from exc
        if result.returncode != 0:
            raise PoemOverlayError(
                f"ffmpeg master overlay failed: {result.stderr.strip()[-800:]}"
            )
    finally:
        if work_dir is None:
            shutil.rmtree(temp_root, ignore_errors=True)

    total_lines = sum(len(lines) for _o, lines in timed_segments)
    return {
        "duration_s": duration,
        "segment_count": len(timed_segments),
        "line_count": total_lines,
        "width": canvas_width,
        "height": canvas_height,
        "audio_replaced": recitation_audio is not None,
        "title_shown": bool(show_title),
        "watermark_shown": bool(clean_watermark),
    }
