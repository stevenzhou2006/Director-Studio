"""Master-level poem finishing: plan, unified recitation, single-pass render."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import settings
from app.core.jobs.poem_finalize import (
    PoemMasterFinishError,
    build_master_finish_plan,
    build_unified_recitation,
    is_poem_project,
)
from app.core.projects.models import Project, Shot, ShotStatus, ShotVoiceRef
from app.core.projects.store import create_project, save_shot
from app.pipelines.poem_overlay import overlay

_FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg required")


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    for name in ("jobs", "library", "projects"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(settings, "jobs_dir", tmp_path / "jobs")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    return tmp_path


def _tone(path: Path, seconds: int, freq: int) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"sine=frequency={freq}:duration={seconds}", str(path)],
        check=True,
    )


def _poem_shot(project_id: str, shot_id: str, line: str) -> Shot:
    shot = Shot(
        id=shot_id,
        project_id=project_id,
        scene_id="sc01",
        title=f"Shot {shot_id}",
        script_beat="recites",
        duration_s=7.5,
        status=ShotStatus.succeeded,
        meta={
            "poem": {
                "title": "相思",
                "author": "王维",
                "dynasty": "唐",
                "seal": "狸",
                "lines": [{"text": line}],
            }
        },
        voice_refs=[
            ShotVoiceRef(
                audio_index=1,
                asset_id=f"voice_{shot_id}",
                file_key="recitation",
            )
        ],
    )
    save_shot(shot)
    return shot


@pytest.fixture
def fake_recitation(monkeypatch, isolated_data):
    audio = isolated_data / "rec.wav"
    _tone(audio, 3, 300)
    monkeypatch.setattr(
        "app.core.jobs.poem_finalize.timing.resolve_recitation_audio",
        lambda shot: (audio, 0.0),
    )
    # Line starts: single line at 1.0s.
    monkeypatch.setattr(
        "app.core.jobs.poem_finalize.timing.derive_line_starts",
        lambda texts, **kw: [1.0 for _ in texts],
    )
    return audio


def _project(tmp_path: str) -> Project:
    proj = create_project("唐诗-相思V1", "红豆生南国")
    return proj


def test_is_poem_project_true(isolated_data):
    proj = _project(isolated_data)
    s1 = _poem_shot(proj.id, "sht_m1", "红豆生南国")
    s2 = _poem_shot(proj.id, "sht_m2", "春来发几枝")
    from app.core.projects.store import save_project

    save_project(proj.model_copy(update={"shot_ids": [s1.id, s2.id]}))
    assert is_poem_project(proj.id) is True


def test_is_poem_project_false_without_meta(isolated_data):
    proj = _project(isolated_data)
    shot = Shot(
        id="sht_plain",
        project_id=proj.id,
        scene_id="sc01",
        title="plain",
        script_beat="walks",
        duration_s=5,
        status=ShotStatus.succeeded,
    )
    save_shot(shot)
    from app.core.projects.store import save_project

    save_project(proj.model_copy(update={"shot_ids": [shot.id]}))
    assert is_poem_project(proj.id) is False


def test_build_master_finish_plan_offsets(isolated_data, fake_recitation):
    proj = _project(isolated_data)
    s1 = _poem_shot(proj.id, "sht_m1", "红豆生南国")
    s2 = _poem_shot(proj.id, "sht_m2", "春来发几枝")
    from app.core.projects.store import save_project

    save_project(proj.model_copy(update={"shot_ids": [s1.id, s2.id]}))
    clips = [
        {"shot_id": s1.id, "duration_s": 7.5},
        {"shot_id": s2.id, "duration_s": 7.5},
    ]
    plan = build_master_finish_plan(proj.id, clips)
    assert plan["total_duration"] == 15.0
    assert plan["segments"][0]["offset_s"] == 0.0
    assert plan["segments"][1]["offset_s"] == 7.5
    # Lines carry LOCAL starts; the renderer adds offset_s for the global time.
    assert plan["segments"][1]["lines"][0]["start_s"] == 1.0
    assert len(plan["audio_parts"]) == 2


def test_build_master_finish_plan_missing_recitation_raises(isolated_data):
    proj = _project(isolated_data)
    shot = Shot(
        id="sht_norec",
        project_id=proj.id,
        scene_id="sc01",
        title="no rec",
        script_beat="recites",
        duration_s=7.5,
        status=ShotStatus.succeeded,
        meta={
            "poem": {
                "title": "相思",
                "author": "王维",
                "lines": [{"text": "红豆生南国"}],
            }
        },
    )
    save_shot(shot)
    with pytest.raises(PoemMasterFinishError):
        build_master_finish_plan(proj.id, [{"shot_id": shot.id, "duration_s": 7.5}])


@needs_ffmpeg
def test_build_unified_recitation_concat(isolated_data):
    a = isolated_data / "a.wav"
    b = isolated_data / "b.wav"
    _tone(a, 2, 300)
    _tone(b, 2, 400)
    out = isolated_data / "unified.m4a"
    build_unified_recitation([(a, 7.5), (b, 7.5)], out)
    dur = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(out)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )
    assert 14.8 <= dur <= 15.2


def _integrated_lufs(path: Path, *, ss: float = 0.0, t: float | None = None) -> float:
    cmd = ["ffmpeg", "-ss", str(ss)]
    if t is not None:
        cmd += ["-t", str(t)]
    cmd += ["-i", str(path), "-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    for line in res.stderr.splitlines():
        if "I:" in line and "LUFS" in line:
            return float(line.split("I:")[1].replace("LUFS", "").strip())
    raise AssertionError("no integrated loudness found")


@needs_ffmpeg
def test_unified_recitation_loudness_normalized(isolated_data):
    # Two takes with a large loudness gap must be normalized to within ~1 LUFS
    # of each other across the segment boundary.
    loud = isolated_data / "loud.wav"
    quiet = isolated_data / "quiet.wav"
    _tone(loud, 2, 300)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(loud),
         "-af", "volume=-9dB", str(quiet)],
        check=True,
    )
    out = isolated_data / "unified.m4a"
    build_unified_recitation([(loud, 2.0), (quiet, 2.0)], out)
    seg1 = _integrated_lufs(out, ss=0.0, t=2.0)
    seg2 = _integrated_lufs(out, ss=2.0, t=2.0)
    assert abs(seg1 - seg2) <= 1.0, (seg1, seg2)


@needs_ffmpeg
def test_render_master_overlay_segments_do_not_overlap(isolated_data):
    """A segment's columns must be gone before the next segment's window starts."""
    from PIL import Image, ImageStat

    base = isolated_data / "base.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=0x808080:s=864x480:d=12", "-r", "24",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)],
        check=True,
    )
    rec = isolated_data / "rec.wav"
    _tone(rec, 11, 300)
    out = isolated_data / "master.mp4"
    overlay.render_master_overlay(
        input_path=base,
        output_path=out,
        title="相思",
        author="王维",
        segments=[
            {"offset_s": 0.0, "lines": [{"text": "红豆生南国", "start_s": 1.0}]},
            {"offset_s": 6.0, "lines": [{"text": "愿君多采撷", "start_s": 1.0}]},
        ],
        recitation_audio=rec,
        show_title=False,
    )
    # Column region on the right side of the frame.
    box = (740, 40, 864, 320)

    def std_at(t: float) -> float:
        frame = isolated_data / f"fr_{t}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(out),
             "-frames:v", "1", str(frame)],
            check=True,
        )
        crop = Image.open(frame).convert("L").crop(box)
        return float(ImageStat.Stat(crop).stddev[0])

    during_seg1 = std_at(3.0)   # seg1 column visible -> high variance
    between = std_at(6.5)      # seg1 faded, seg2 line not until 7.0 -> ~flat
    assert during_seg1 > 8.0, during_seg1
    assert between < 3.0, between


@needs_ffmpeg
def test_render_master_overlay_title_once_and_watermark(isolated_data):
    base = isolated_data / "base.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=0x203040:s=864x480:d=15", "-r", "24",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)],
        check=True,
    )
    rec = isolated_data / "rec.m4a"
    _tone(isolated_data / "recsrc.wav", 14, 300)
    shutil.copyfile(isolated_data / "recsrc.wav", rec)
    out = isolated_data / "master.mp4"
    meta = overlay.render_master_overlay(
        input_path=base,
        output_path=out,
        title="相思",
        author="王维",
        segments=[
            {"offset_s": 0.0, "lines": [{"text": "红豆生南国", "start_s": 1.0},
                                        {"text": "春来发几枝", "start_s": 4.0}]},
            {"offset_s": 7.5, "lines": [{"text": "愿君多采撷", "start_s": 0.5},
                                       {"text": "此物最相思", "start_s": 3.5}]},
        ],
        recitation_audio=rec,
        watermark="@大狸小白",
        show_title=True,
    )
    assert meta["title_shown"] is True
    assert meta["watermark_shown"] is True
    assert meta["segment_count"] == 2
    assert meta["line_count"] == 4
    assert out.is_file()
