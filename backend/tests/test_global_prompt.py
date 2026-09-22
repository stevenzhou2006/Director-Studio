from __future__ import annotations

from app.config import settings
from app.core.h3.prompt import compose_h3_prompt, validate_h3_prompt
from app.core.projects.models import PromptSections
from app.core.projects.store import create_project, load_project, save_project
from app.core.prompting import (
    append_global_prompt,
    effective_global_negative,
    effective_global_prompt,
    ensure_global_prompt_in_h3,
    global_prompt_block,
    load_app_global_prompt,
    load_app_global_negative,
    save_app_global_direction,
    save_app_global_prompt,
)


def _sections() -> PromptSections:
    return PromptSections(
        subject_definitions="<Picture 1> defines the subject.",
        summary="A short shot.",
        retention_analysis="Retain identity and geography.",
        detailed_description="0-4 seconds: the subject acts.",
        overall_soundscape="Room tone.",
        non_diegetic_music="No non-diegetic music.",
    )


def test_global_prompt_block_empty_when_unset():
    assert global_prompt_block("") == ""
    assert "GLOBAL DIRECTION" in global_prompt_block("Always teal.")


def test_append_global_prompt_appends_once():
    base = "A photo of a room."
    out = append_global_prompt(base, "Cinematic teal grade.")
    assert out.startswith(base)
    assert "Cinematic teal grade." in out
    assert append_global_prompt(out, "Cinematic teal grade.") == out


def test_append_global_prompt_noop_when_unset():
    assert append_global_prompt("x", "") == "x"
    assert append_global_prompt("", "") == ""


def test_ensure_global_prompt_in_h3_keeps_prompt_valid_and_dedupes():
    prompt = compose_h3_prompt(_sections())
    out = ensure_global_prompt_in_h3(prompt, "Keep the same custom widget.")
    assert "custom widget" in out
    # Prepending before the first section header must still validate.
    validate_h3_prompt(out, [])
    # Re-applying must not duplicate.
    assert ensure_global_prompt_in_h3(out, "Keep the same custom widget.") == out


def test_app_global_prompt_round_trips_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert load_app_global_prompt() == ""
    saved = save_app_global_prompt("  Soft amber grade, no on-screen text.  ")
    assert saved == "Soft amber grade, no on-screen text."
    assert load_app_global_prompt() == "Soft amber grade, no on-screen text."


def test_effective_global_prompt_precedence(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(settings, "projects_dir", projects)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "global_prompt", "ENV DEFAULT")

    # Only the environment default is set.
    assert effective_global_prompt(None) == "ENV DEFAULT"

    # Persisted app-wide value overrides the environment default.
    save_app_global_prompt("APP-WIDE")
    assert effective_global_prompt(None) == "APP-WIDE"

    project = create_project("Global prompt project", "script")
    assert effective_global_prompt(project.id) == "APP-WIDE"

    # A per-project override wins over the app-wide value.
    saved = load_project(project.id)
    assert saved is not None
    save_project(saved.model_copy(update={"global_prompt": "PROJECT OVERRIDE"}))
    assert effective_global_prompt(project.id) == "PROJECT OVERRIDE"

    # An explicit value always wins.
    assert effective_global_prompt(project.id, explicit="EXPLICIT") == "EXPLICIT"


def test_effective_global_negative_precedence(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(settings, "projects_dir", projects)
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    assert effective_global_negative(None) == ""

    save_app_global_direction(negative="APP NEGATIVE")
    assert load_app_global_negative() == "APP NEGATIVE"
    assert effective_global_negative(None) == "APP NEGATIVE"

    project = create_project("Negative project", "script")
    assert effective_global_negative(project.id) == "APP NEGATIVE"

    saved = load_project(project.id)
    assert saved is not None
    save_project(saved.model_copy(update={"global_negative": "PROJECT NEGATIVE"}))
    assert effective_global_negative(project.id) == "PROJECT NEGATIVE"
    assert effective_global_negative(project.id, explicit="EXPLICIT") == "EXPLICIT"
