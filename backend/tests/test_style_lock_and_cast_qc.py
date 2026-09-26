from __future__ import annotations

from app.agents.director.service import _poem_title_card_intent
from app.agents.director.tool_schema import director_tool_schemas
from app.core.projects.models import Project, ProjectMode, Shot, ShotStatus
from app.core.projects.store import save_project
from app.core.prompting import (
    SCENE_STYLE_AUTHORITY_MARKER,
    STYLE_LOCK_MARKER,
    append_scene_style_authority,
    append_style_lock,
    effective_style_lock,
    scene_style_authority_block,
    style_lock_block,
)


def _shot(**overrides) -> Shot:
    base = dict(
        id="sht_1",
        project_id="prj_1",
        scene_id="scn_1",
        title="Line 1",
        script_beat="dali recites the first line",
        duration_s=3.0,
        status=ShotStatus.draft,
    )
    base.update(overrides)
    return Shot(**base)


def test_style_lock_block_and_append():
    assert style_lock_block("") == ""
    block = style_lock_block("ink-wash")
    assert STYLE_LOCK_MARKER in block and "ink-wash" in block
    merged = append_style_lock("base prompt", "ink-wash")
    assert merged.startswith("base prompt") and STYLE_LOCK_MARKER in merged
    # de-duplicated: appending twice keeps a single marker
    twice = append_style_lock(merged, "ink-wash")
    assert twice.count(STYLE_LOCK_MARKER) == 1
    assert append_style_lock("base", "") == "base"


def test_scene_style_authority_block_and_append():
    block = scene_style_authority_block()
    assert SCENE_STYLE_AUTHORITY_MARKER in block
    merged = append_scene_style_authority("base prompt")
    assert merged.startswith("base prompt") and SCENE_STYLE_AUTHORITY_MARKER in merged
    # de-duplicated: appending twice keeps a single marker
    twice = append_scene_style_authority(merged)
    assert twice.count(SCENE_STYLE_AUTHORITY_MARKER) == 1


def test_effective_style_lock_is_explicit_only(tmp_projects_dir):
    project = Project(
        id="prj_style_1",
        name="p",
        script_text="水墨风格 青绿设色",
        mode=ProjectMode.director,
        created_at="x",
        updated_at="x",
    )
    save_project(project)
    # No explicit lock: nothing is derived from the script prose.
    assert effective_style_lock("prj_style_1") == ""
    save_project(project.model_copy(update={"style_lock": "oil painting"}))
    assert effective_style_lock("prj_style_1") == "oil painting"


def test_poem_title_card_intent():
    assert _poem_title_card_intent(
        _shot(script_beat="Title card reads 《相思》 with 唐 · 王维")
    )
    assert _poem_title_card_intent(_shot(title="片头标题"))
    assert _poem_title_card_intent(_shot(script_beat="show the author attribution"))
    assert not _poem_title_card_intent(_shot(script_beat="dali walks across the room"))


def test_new_tools_are_exposed():
    project = Project(
        id="prj_tools_1",
        name="p",
        script_text="s",
        mode=ProjectMode.director,
        created_at="x",
        updated_at="x",
    )
    names = {t["function"]["name"] for t in director_tool_schemas(project)}
    assert {"set_style_lock", "qc_layout"} <= names
    layout_turn = {
        t["function"]["name"]
        for t in director_tool_schemas(
            project, current_message="shot 1 风格不统一，画风要一致"
        )
    }
    assert {"set_style_lock", "qc_layout"} <= layout_turn
