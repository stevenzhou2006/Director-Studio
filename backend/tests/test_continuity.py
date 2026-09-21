from __future__ import annotations

from app.core.projects.continuity import (
    CastAnchor,
    LocationAnchor,
    ProjectContinuity,
    PropAnchor,
    apply_continuity_to_shot,
    continuity_hint,
    derive_continuity,
)
from app.core.projects.models import RefRole, Shot, ShotRef
from app.core.schemas import LibraryAsset


def _actor(asset_id: str, name: str, **files: str) -> LibraryAsset:
    return LibraryAsset(
        id=asset_id,
        kind="actors",
        name=name,
        pipeline_id="actor",
        job_id="job_" + asset_id,
        created_at="2026-01-01T00:00:00+00:00",
        files=dict(files),
    )


def _scene(asset_id: str, name: str, **files: str) -> LibraryAsset:
    return LibraryAsset(
        id=asset_id,
        kind="scenes",
        name=name,
        pipeline_id="scene",
        job_id="job_" + asset_id,
        created_at="2026-01-01T00:00:00+00:00",
        files=dict(files),
    )


def _prop(asset_id: str, name: str, **files: str) -> LibraryAsset:
    return LibraryAsset(
        id=asset_id,
        kind="props",
        name=name,
        pipeline_id="prop",
        job_id="job_" + asset_id,
        created_at="2026-01-01T00:00:00+00:00",
        files=dict(files),
    )


def _shot(scene_id: str, refs: list[ShotRef]) -> Shot:
    return Shot(
        id="sht_x",
        project_id="prj_x",
        scene_id=scene_id,
        title="t",
        script_beat="b",
        duration_s=6.0,
        refs=refs,
    )


def test_derive_records_prop_anchor() -> None:
    widget = _prop("prp_widget", "Widget", master="widget.png")
    index = {widget.id: widget}
    shots = [
        _shot(
            "sc01",
            [
                ShotRef(
                    role=RefRole.prop,
                    asset_id=widget.id,
                    picture_index=1,
                    file_key="master",
                )
            ],
        )
    ]
    continuity = derive_continuity("prj_x", shots, index)
    assert continuity.props_by_key()["widget"].asset_id == widget.id
    assert continuity.props_by_key()["widget"].file_key == "master"


def test_apply_pins_deviating_prop_back_to_anchor() -> None:
    widget = _prop("prp_widget", "Widget", master="widget.png")
    other = _prop("prp_widget_other", "Widget", master="other_widget.png")
    index = {widget.id: widget, other.id: other}
    continuity = ProjectContinuity(
        project_id="prj_x",
        props=[
            PropAnchor(
                prop_key="widget",
                asset_id=widget.id,
                file_key="master",
                display_name="Widget",
            )
        ],
    )
    shot = _shot(
        "sc01",
        [ShotRef(role=RefRole.prop, asset_id=other.id, picture_index=1)],
    )
    updated, notes = apply_continuity_to_shot(shot, continuity, index)
    assert updated.refs[0].asset_id == widget.id
    assert any("prop" in note for note in notes)


def test_continuity_hint_lists_locked_props() -> None:
    continuity = ProjectContinuity(
        project_id="prj_x",
        props=[
            PropAnchor(
                prop_key="widget",
                asset_id="prp_widget",
                file_key="master",
                display_name="Widget",
            )
        ],
    )
    hint = continuity_hint(continuity)
    assert "prp_widget" in hint
    assert "Widget" in hint

def test_derive_records_first_actor_view_and_scene_asset() -> None:
    mia = _actor("act_mia", "Mia", master="m.png", fullbody_threeview="fv.png")
    room = _scene("scn_room", "Room", master="r.png")
    index = {mia.id: mia, room.id: room}
    shots = [
        _shot(
            "sc01",
            [
                ShotRef(
                    role=RefRole.actor,
                    asset_id=mia.id,
                    picture_index=1,
                    file_key="fullbody_threeview",
                ),
                ShotRef(role=RefRole.scene, asset_id=room.id, picture_index=2),
            ],
        )
    ]
    continuity = derive_continuity("prj_x", shots, index)
    assert continuity.cast_by_key()["mia"].file_key == "fullbody_threeview"
    assert continuity.location_by_key()["sc01"].asset_id == room.id


def test_apply_pins_deviating_actor_view_back_to_anchor() -> None:
    mia = _actor("act_mia", "Mia", master="m.png", fullbody_threeview="fv.png")
    index = {mia.id: mia}
    continuity = ProjectContinuity(
        project_id="prj_x",
        cast=[
            CastAnchor(
                character_key="mia",
                asset_id=mia.id,
                file_key="fullbody_threeview",
                display_name="Mia",
            )
        ],
    )
    shot = _shot(
        "sc01",
        [
            ShotRef(
                role=RefRole.actor,
                asset_id=mia.id,
                picture_index=1,
                file_key="master",
            )
        ],
    )
    updated, notes = apply_continuity_to_shot(shot, continuity, index)
    assert updated.refs[0].file_key == "fullbody_threeview"
    assert any("fullbody_threeview" in note for note in notes)


def test_apply_pins_deviating_scene_asset_back_to_anchor() -> None:
    room_a = _scene("scn_a", "Room A", master="a.png")
    room_b = _scene("scn_b", "Room B", master="b.png")
    index = {room_a.id: room_a, room_b.id: room_b}
    continuity = ProjectContinuity(
        project_id="prj_x",
        locations=[
            LocationAnchor(
                scene_id="sc01",
                scene_key="sc01",
                asset_id=room_a.id,
                display_name="Room A",
            )
        ],
    )
    shot = _shot(
        "sc01",
        [ShotRef(role=RefRole.scene, asset_id=room_b.id, picture_index=1)],
    )
    updated, notes = apply_continuity_to_shot(shot, continuity, index)
    assert updated.refs[0].asset_id == room_a.id
    assert any("sc01" in note for note in notes)


def test_apply_skips_when_anchor_asset_missing_from_index() -> None:
    mia = _actor("act_mia", "Mia", master="m.png")
    index = {mia.id: mia}
    continuity = ProjectContinuity(
        project_id="prj_x",
        cast=[
            CastAnchor(
                character_key="mia",
                asset_id="act_deleted",
                file_key="fullbody_threeview",
                display_name="Mia",
            )
        ],
    )
    shot = _shot(
        "sc01",
        [ShotRef(role=RefRole.actor, asset_id=mia.id, picture_index=1)],
    )
    updated, notes = apply_continuity_to_shot(shot, continuity, index)
    assert updated.refs[0].asset_id == mia.id
    assert notes == []


def test_apply_does_not_duplicate_existing_binding() -> None:
    mia = _actor("act_mia", "Mia", master="m.png", fullbody_threeview="fv.png")
    other = _actor("act_other", "Mia", master="o.png")
    index = {mia.id: mia, other.id: other}
    continuity = ProjectContinuity(
        project_id="prj_x",
        cast=[
            CastAnchor(
                character_key="mia",
                asset_id=mia.id,
                file_key="master",
                display_name="Mia",
            )
        ],
    )
    shot = _shot(
        "sc01",
        [
            ShotRef(role=RefRole.actor, asset_id=mia.id, picture_index=1),
            ShotRef(role=RefRole.actor, asset_id=other.id, picture_index=2),
        ],
    )
    updated, _notes = apply_continuity_to_shot(shot, continuity, index)
    asset_ids = [ref.asset_id for ref in updated.refs]
    assert len(asset_ids) == len(set(asset_ids))


def test_continuity_hint_lists_locked_cast_and_locations() -> None:
    continuity = ProjectContinuity(
        project_id="prj_x",
        cast=[
            CastAnchor(
                character_key="mia",
                asset_id="act_mia",
                file_key="fullbody_threeview",
                display_name="Mia",
            )
        ],
        locations=[
            LocationAnchor(
                scene_id="sc01",
                scene_key="sc01",
                asset_id="scn_room",
                display_name="Room",
            )
        ],
    )
    hint = continuity_hint(continuity)
    assert "act_mia" in hint
    assert "fullbody_threeview" in hint
    assert "scn_room" in hint
    assert continuity_hint(None) == ""
