"""Agent-cast shot.refs drive ref_frame image pack (not hardcoded role filter)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest

from app.agents.director.service import DirectorService
from app.core.projects.models import PromptSections, RefRole, Shot, ShotRef, ShotStatus
from app.core.schemas import LibraryAsset


class _NoopProvider:
    async def complete(
        self,
        system: str,
        user: str,
        *,
        guides: Iterable[str] = (),
    ) -> str:
        return "[]"


def _png_bytes() -> bytes:
    # Minimal valid-ish payload; collector only needs non-empty bytes
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> DirectorService:
    s = DirectorService(plan_provider=_NoopProvider())
    def _asset(id_: str, kind: str, name: str, files: dict[str, str]) -> LibraryAsset:
        return LibraryAsset(
            id=id_,
            kind=kind,
            name=name,
            files=files,
            pipeline_id="test",
            job_id="job_test",
            created_at="2026-01-01T00:00:00+00:00",
        )

    assets = {
        "act_a": _asset("act_a", "actors", "girl", {"master": "master.png"}),
        "scn_b": _asset("scn_b", "scenes", "corridor", {"master": "master.png"}),
        "prp_c": _asset("prp_c", "props", "deodorant", {"master": "master.jpg"}),
    }

    def fake_load(kind: str, asset_id: str):
        a = assets.get(asset_id)
        if a and a.kind == kind:
            return a
        # allow cross-kind search loop
        return assets.get(asset_id)

    def fake_read(asset: LibraryAsset, *, role: str | None = None, file_key: str | None = None):
        return ("x.png", _png_bytes())

    def fake_actor(asset, *, preferred_key=None):
        return ("actor.png", _png_bytes(), preferred_key or "master")

    def fake_scene(asset, *, preferred_key=None):
        return ("scene.png", _png_bytes(), preferred_key or "master")

    monkeypatch.setattr(
        "app.agents.director.service.load_asset", fake_load
    )
    monkeypatch.setattr(
        "app.agents.director.service._read_asset_image_bytes", fake_read
    )
    monkeypatch.setattr(
        "app.agents.director.service._actor_image_for_ref_frame", fake_actor
    )
    monkeypatch.setattr(
        "app.agents.director.service._scene_image_for_ref_frame", fake_scene
    )
    return s


def test_collect_uses_scene_actor_and_action_prop_images(svc: DirectorService):
    """A selected handled prop uses the third Qwen image slot when available."""
    shot = Shot(
        id="sht_agent_cast",
        project_id="prj_t",
        scene_id="sc01",
        title="spray",
        script_beat="spray deodorant",
        duration_s=5.0,
        status=ShotStatus.ref_frame_pending,
        refs=[
            # Deliberately out of role-priority order in the list
            ShotRef(role=RefRole.prop, asset_id="prp_c", picture_index=3, file_key="master"),
            ShotRef(role=RefRole.actor, asset_id="act_a", picture_index=2, file_key="master"),
            ShotRef(role=RefRole.scene, asset_id="scn_b", picture_index=1, file_key="master"),
        ],
        prompt_sections=PromptSections(),
    )
    packed = svc._collect_ref_frame_refs(shot)
    assert list(packed["images"].keys()) == ["ref_0", "ref_1", "ref_2"]
    img_labels = [L for L in packed["labels"] if L.startswith("Image")]
    assert len(img_labels) == 3
    assert "SCENE" in packed["labels"][0] and "corridor" in packed["labels"][0]
    assert "CHARACTER" in packed["labels"][1] and "girl" in packed["labels"][1]
    assert "PROP" in packed["labels"][2] and "deodorant" in packed["labels"][2]
    assert "according to the shot action" in packed["labels"][2]
    assert "in the character's hand" not in packed["labels"][2]


def test_collect_honors_agent_selected_actor_and_scene_file_keys(svc: DirectorService):
    shot = Shot(
        id="sht_exact_files",
        project_id="prj_t",
        scene_id="sc01",
        title="selected angles",
        script_beat="actor crosses the corridor",
        duration_s=5.0,
        status=ShotStatus.ref_frame_pending,
        refs=[
            ShotRef(
                role=RefRole.scene,
                asset_id="scn_b",
                picture_index=1,
                file_key="right_view",
            ),
            ShotRef(
                role=RefRole.actor,
                asset_id="act_a",
                picture_index=2,
                file_key="fullbody_threeview",
            ),
        ],
        prompt_sections=PromptSections(),
    )

    packed = svc._collect_ref_frame_refs(shot)

    assert "right_view" in packed["image_labels"][0]
    assert "fullbody_threeview" in packed["image_labels"][1]


def test_collect_skips_layout_output_role(svc: DirectorService):
    shot = Shot(
        id="sht_layout_skip",
        project_id="prj_t",
        scene_id="sc01",
        title="t",
        script_beat="b",
        duration_s=5.0,
        status=ShotStatus.ref_frame_pending,
        refs=[
            ShotRef(role=RefRole.layout_ref_frame, asset_id="lay_x", picture_index=1),
            ShotRef(role=RefRole.scene, asset_id="scn_b", picture_index=2),
            ShotRef(role=RefRole.actor, asset_id="act_a", picture_index=3),
        ],
        prompt_sections=PromptSections(),
    )
    packed = svc._collect_ref_frame_refs(shot)
    assert len(packed["images"]) == 2
    assert all("lay_" not in lab for lab in packed["labels"] if lab.startswith("Image"))


def test_collect_packs_two_actors_and_keeps_the_prop_attached(monkeypatch) -> None:
    import io

    from PIL import Image

    def png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (width, height), color).save(buf, format="PNG")
        return buf.getvalue()

    svc = DirectorService(plan_provider=_NoopProvider())
    assets = {
        "act_a": LibraryAsset(
            id="act_a", kind="actors", name="Dali",
            files={"fullbody_threeview": "x.png"}, pipeline_id="actor",
            job_id="j", created_at="2026-01-01T00:00:00+00:00",
            meta={"species": "quadruped", "description": ""},
        ),
        "act_b": LibraryAsset(
            id="act_b", kind="actors", name="xiaobai",
            files={"fullbody_threeview": "x.png"}, pipeline_id="actor",
            job_id="j", created_at="2026-01-01T00:00:00+00:00",
            meta={"species": "quadruped", "description": ""},
        ),
        "scn_s": LibraryAsset(
            id="scn_s", kind="scenes", name="garage",
            files={"master": "x.png"}, pipeline_id="test",
            job_id="j", created_at="2026-01-01T00:00:00+00:00",
        ),
        "prp_p": LibraryAsset(
            id="prp_p", kind="props", name="psu",
            files={"master": "x.png"}, pipeline_id="external",
            job_id="", created_at="2026-01-01T00:00:00+00:00",
        ),
    }

    def fake_load(kind: str, asset_id: str):
        a = assets.get(asset_id)
        return a if a and a.kind == kind else None

    monkeypatch.setattr("app.agents.director.service.load_asset", fake_load)
    monkeypatch.setattr(
        "app.agents.director.service._actor_image_for_ref_frame",
        lambda asset, preferred_key=None: (
            "actor.png", png(200, 400, (200, 120, 60)), "fullbody_threeview->front_crop",
        ),
    )
    monkeypatch.setattr(
        "app.agents.director.service._scene_image_for_ref_frame",
        lambda asset, preferred_key=None: ("scene.png", png(800, 450, (60, 60, 60)), "master"),
    )
    monkeypatch.setattr(
        "app.agents.director.service._read_asset_image_bytes",
        lambda asset, role=None, file_key=None: ("prop.png", png(400, 400, (120, 120, 120))),
    )

    shot = Shot(
        id="sht_prop",
        project_id="prj_t",
        scene_id="sc01",
        title="psu",
        script_beat="two cats beside a psu",
        duration_s=15.0,
        status=ShotStatus.ref_frame_pending,
        refs=[
            ShotRef(role=RefRole.actor, asset_id="act_a", picture_index=1, file_key="master"),
            ShotRef(role=RefRole.actor, asset_id="act_b", picture_index=2, file_key="master"),
            ShotRef(role=RefRole.prop, asset_id="prp_p", picture_index=3, file_key="master"),
            ShotRef(role=RefRole.scene, asset_id="scn_s", picture_index=4, file_key="master"),
        ],
        prompt_sections=PromptSections(),
    )

    packed = svc._collect_ref_frame_refs(shot)

    assert list(packed["images"].keys()) == ["ref_0", "ref_1", "ref_2"]
    labels = packed["labels"]
    assert any(
        "CHARACTERS x2" in label and "Dali" in label and "xiaobai" in label
        for label in labels
    )
    assert any("PROP" in label and "psu" in label for label in labels)
    by_asset = {ref.asset_id: ref for ref in packed["source_refs"]}
    assert by_asset["act_a"].image_index == 2
    assert by_asset["act_b"].image_index == 2
    assert by_asset["scn_s"].image_index == 1
    assert by_asset["prp_p"].image_index == 3


def test_collect_keeps_two_human_actors_separate(monkeypatch) -> None:
    import io

    from PIL import Image

    def png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (width, height), color).save(buf, format="PNG")
        return buf.getvalue()

    svc = DirectorService(plan_provider=_NoopProvider())
    assets = {
        "act_a": LibraryAsset(
            id="act_a", kind="actors", name="Mia",
            files={"fullbody_threeview": "x.png"}, pipeline_id="actor",
            job_id="j", created_at="2026-01-01T00:00:00+00:00",
            meta={"species": "human", "description": "Mia, a woman"},
        ),
        "act_b": LibraryAsset(
            id="act_b", kind="actors", name="Kai",
            files={"fullbody_threeview": "x.png"}, pipeline_id="actor",
            job_id="j", created_at="2026-01-01T00:00:00+00:00",
            meta={"species": "human", "description": "Kai, a man"},
        ),
        "scn_s": LibraryAsset(
            id="scn_s", kind="scenes", name="garage",
            files={"master": "x.png"}, pipeline_id="test",
            job_id="j", created_at="2026-01-01T00:00:00+00:00",
        ),
        "prp_p": LibraryAsset(
            id="prp_p", kind="props", name="psu",
            files={"master": "x.png"}, pipeline_id="external",
            job_id="", created_at="2026-01-01T00:00:00+00:00",
        ),
    }

    def fake_load(kind: str, asset_id: str):
        a = assets.get(asset_id)
        return a if a and a.kind == kind else None

    monkeypatch.setattr("app.agents.director.service.load_asset", fake_load)
    monkeypatch.setattr(
        "app.agents.director.service._actor_image_for_ref_frame",
        lambda asset, preferred_key=None: (
            "actor.png", png(200, 400, (200, 120, 60)), "fullbody_threeview->front_crop",
        ),
    )
    monkeypatch.setattr(
        "app.agents.director.service._scene_image_for_ref_frame",
        lambda asset, preferred_key=None: ("scene.png", png(800, 450, (60, 60, 60)), "master"),
    )
    monkeypatch.setattr(
        "app.agents.director.service._read_asset_image_bytes",
        lambda asset, role=None, file_key=None: ("prop.png", png(400, 400, (120, 120, 120))),
    )

    shot = Shot(
        id="sht_humans",
        project_id="prj_t",
        scene_id="sc01",
        title="psu",
        script_beat="two people beside a psu",
        duration_s=15.0,
        status=ShotStatus.ref_frame_pending,
        refs=[
            ShotRef(role=RefRole.actor, asset_id="act_a", picture_index=1, file_key="master"),
            ShotRef(role=RefRole.actor, asset_id="act_b", picture_index=2, file_key="master"),
            ShotRef(role=RefRole.prop, asset_id="prp_p", picture_index=3, file_key="master"),
            ShotRef(role=RefRole.scene, asset_id="scn_s", picture_index=4, file_key="master"),
        ],
        prompt_sections=PromptSections(),
    )

    packed = svc._collect_ref_frame_refs(shot)

    # Human casts keep the original one-image-per-actor packing: the prop is
    # still text-only and no actor composite is produced.
    assert list(packed["images"].keys()) == ["ref_0", "ref_1", "ref_2"]
    assert not any("CHARACTERS x2" in label for label in packed["labels"])
    assert any("PROP text only" in label for label in packed["labels"])
    assert all(ref.role != RefRole.prop for ref in packed["source_refs"])
    assert [ref.image_index for ref in packed["source_refs"]] == [None, None, None]


def _scene_asset() -> LibraryAsset:
    return LibraryAsset(
        id="scn_trike",
        kind="scenes",
        name="trike",
        files={
            "input_scene": "input_scene.jpeg",
            "master": "master.jpeg",
            "三轮车_01_left_side_view_h270_v0": "a.png",
            "三轮车_04_front_left_view_h315_v0": "b.png",
        },
        pipeline_id="scene",
        job_id="job_scene",
        created_at="2026-01-01T00:00:00+00:00",
    )


def test_scene_image_demotes_side_view_preferred_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rear/side plate hides the driver area, so the model invents a cab."""
    from app.agents.director import reference_service as rs

    requested: list[str] = []

    def fake_resolve(asset, *, role=None, file_key=None):
        requested.append(file_key)
        if file_key in asset.files:
            return (f"{file_key}.png", b"data", file_key)
        return None

    monkeypatch.setattr("app.core.library.images.resolve_asset_image", fake_resolve)

    name, data, used = rs._scene_image_for_ref_frame(
        _scene_asset(), preferred_key="三轮车_01_left_side_view_h270_v0"
    )

    assert used == "input_scene"
    assert requested[0] == "input_scene"


def test_scene_image_honors_frontal_preferred_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.director import reference_service as rs

    requested: list[str] = []

    def fake_resolve(asset, *, role=None, file_key=None):
        requested.append(file_key)
        if file_key in asset.files:
            return (f"{file_key}.png", b"data", file_key)
        return None

    monkeypatch.setattr("app.core.library.images.resolve_asset_image", fake_resolve)

    name, data, used = rs._scene_image_for_ref_frame(
        _scene_asset(), preferred_key="三轮车_04_front_left_view_h315_v0"
    )

    assert used == "三轮车_04_front_left_view_h315_v0"
    assert requested[0] == "三轮车_04_front_left_view_h315_v0"


def test_actor_image_prefers_quadruped_threeview_over_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.director import reference_service as rs

    cat = LibraryAsset(
        id="act_cat",
        kind="actors",
        name="Dali",
        files={"master": "master.png", "fullbody_threeview": "fullbody_threeview.png"},
        pipeline_id="actor",
        job_id="job_cat",
        created_at="2026-01-01T00:00:00+00:00",
        meta={"species": "quadruped", "description": ""},
    )
    requested: list[str] = []

    def fake_resolve(asset, *, role=None, file_key=None):
        requested.append(file_key)
        if file_key in {"master", "fullbody_threeview"}:
            return (f"{file_key}.png", b"data", file_key)
        return None

    monkeypatch.setattr(
        "app.core.library.images.resolve_asset_image", fake_resolve
    )
    monkeypatch.setattr(
        rs,
        "_crop_sheet_front_panel",
        lambda data, force=False: ("crop.png", b"crop"),
    )

    name, data, used = rs._actor_image_for_ref_frame(cat, preferred_key="master")

    assert used == "fullbody_threeview->front_crop"
    assert "master" not in requested


def test_collect_describes_quadruped_actor_as_an_animal(
    svc: DirectorService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.pipelines.actor.workflow import DEFAULT_DESCRIPTION

    cat = LibraryAsset(
        id="act_cat",
        kind="actors",
        name="Dali",
        files={"fullbody_threeview": "fullbody_threeview.png"},
        pipeline_id="actor",
        job_id="job_cat",
        created_at="2026-01-01T00:00:00+00:00",
        meta={"species": "quadruped", "description": DEFAULT_DESCRIPTION},
    )
    scene = LibraryAsset(
        id="scn_garage",
        kind="scenes",
        name="garage",
        files={"master": "master.png"},
        pipeline_id="test",
        job_id="job_scene",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assets = {"act_cat": cat, "scn_garage": scene}

    def fake_load(kind: str, asset_id: str):
        a = assets.get(asset_id)
        return a if a and a.kind == kind else None

    monkeypatch.setattr("app.agents.director.service.load_asset", fake_load)

    shot = Shot(
        id="sht_cats",
        project_id="prj_t",
        scene_id="sc01",
        title="psu",
        script_beat="two cats beside a psu",
        duration_s=15.0,
        status=ShotStatus.ref_frame_pending,
        refs=[
            ShotRef(
                role=RefRole.scene,
                asset_id="scn_garage",
                picture_index=1,
                file_key="master",
            ),
            ShotRef(
                role=RefRole.actor,
                asset_id="act_cat",
                picture_index=2,
                file_key="fullbody_threeview",
            ),
        ],
        prompt_sections=PromptSections(),
    )

    packed = svc._collect_ref_frame_refs(shot)
    character_label = next(
        label
        for label in packed["labels"]
        if label.startswith("Image") and "CHARACTER" in label
    )
    lowered = character_label.lower()
    assert "animal" in lowered
    assert "all fours" in lowered
    assert "no human" in lowered
    # The generic human casting boilerplate must not leak in.
    assert "body person" not in lowered
    assert "one adult" not in lowered
    assert "exactly one person" not in lowered
