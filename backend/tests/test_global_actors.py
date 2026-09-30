"""Global Asset library for actors: publish/withdraw + cross-project usage."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.library.store import new_asset_id, write_asset
from app.core.projects.models import Shot
from app.core.projects.store import create_project, save_shot
from app.core.schemas import LibraryAsset


@pytest.fixture
def global_env(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    jobs = tmp_path / "jobs"
    library = tmp_path / "library"
    projects.mkdir()
    jobs.mkdir()
    library.mkdir()
    monkeypatch.setattr(settings, "projects_dir", projects)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return {"projects": projects, "jobs": jobs, "library": library}


@pytest.fixture
def client(global_env):
    from app.agents.director.service import DirectorService
    from app.main import create_app

    class RaisingProvider:
        async def complete(self, system, user, *, guides=()):
            raise AssertionError("LLM must not be called in global-actor tests")

    class SilentOrch:
        async def release_llm(self):
            return None

        async def ensure_llm_ready(self):
            return None

        class _Sess:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

        def llm_session(self, *, release_on_exit: bool = True):
            return self._Sess()

    app = create_app()
    app.state.director_service = DirectorService(
        plan_provider=RaisingProvider(), orchestrator=SilentOrch()
    )
    with TestClient(app) as c:
        yield c


def make_actor(name: str, project_id: str | None, **updates) -> LibraryAsset:
    asset_id = new_asset_id("actors")
    asset = LibraryAsset(
        id=asset_id,
        kind="actors",
        name=name,
        pipeline_id="actor",
        job_id="job_test",
        created_at="2026-09-30T00:00:00+00:00",
        files={"master": f"{asset_id}.png", "fullbody_threeview": f"{asset_id}_fb.png"},
        project_id=project_id,
        **updates,
    )
    return write_asset(asset)


def make_scene(name: str, project_id: str) -> LibraryAsset:
    asset_id = new_asset_id("scenes")
    asset = LibraryAsset(
        id=asset_id,
        kind="scenes",
        name=name,
        pipeline_id="scene",
        job_id="job_test",
        created_at="2026-09-30T00:00:00+00:00",
        files={"master": f"{asset_id}.png"},
        project_id=project_id,
    )
    return write_asset(asset)


def make_shot(project_id: str, shot_id: str) -> Shot:
    shot = Shot(
        id=shot_id,
        project_id=project_id,
        scene_id="sc_test",
        title="Test shot",
        script_beat="A test beat",
        duration_s=5.0,
    )
    save_shot(shot)
    return shot


def test_legacy_asset_defaults_not_global():
    asset = LibraryAsset(
        id="act_x", kind="actors", name="x", pipeline_id="actor", job_id="j", created_at="t"
    )
    assert asset.is_global is False


def test_publish_makes_actor_visible_in_other_project(client):
    alpha = create_project("Alpha", "First film")
    beta = create_project("Beta", "Second film")
    actor = make_actor("Hero", alpha.id)

    r = client.get(f"/api/library?kind=actors&project_id={beta.id}")
    assert actor.id not in [x["id"] for x in r.json()]

    r = client.patch(f"/api/library/actors/{actor.id}/global", json={"is_global": True})
    assert r.status_code == 200
    assert r.json()["asset"]["is_global"] is True

    r = client.get(f"/api/library?kind=actors&project_id={beta.id}")
    assert actor.id in [x["id"] for x in r.json()]

    r = client.get(f"/api/actors?project_id={beta.id}")
    items = {x["id"]: x for x in r.json()["items"]}
    assert items[actor.id]["is_global"] is True
    assert items[actor.id]["project_id"] == alpha.id


def test_unpublish_removes_from_other_projects(client):
    alpha = create_project("Alpha", "First film")
    beta = create_project("Beta", "Second film")
    actor = make_actor("Hero", alpha.id)
    client.patch(f"/api/library/actors/{actor.id}/global", json={"is_global": True})

    r = client.patch(f"/api/library/actors/{actor.id}/global", json={"is_global": False})
    assert r.status_code == 200
    assert r.json()["asset"]["is_global"] is False

    r = client.get(f"/api/library?kind=actors&project_id={beta.id}")
    assert actor.id not in [x["id"] for x in r.json()]

    r = client.get(f"/api/library?kind=actors&project_id={alpha.id}")
    assert actor.id in [x["id"] for x in r.json()]


def test_global_publishing_rejects_non_actors(client):
    alpha = create_project("Alpha", "First film")
    scene = make_scene("Room", alpha.id)
    r = client.patch(f"/api/library/scenes/{scene.id}/global", json={"is_global": True})
    assert r.status_code == 400


def test_shot_materials_accept_global_actor_cross_project(client):
    alpha = create_project("Alpha", "First film")
    beta = create_project("Beta", "Second film")
    actor = make_actor("Hero", alpha.id)
    shot = make_shot(beta.id, "sht_beta")

    r = client.put(
        f"/api/shots/{shot.id}/materials",
        json={"materials": [{"role": "actor", "asset_id": actor.id}]},
    )
    assert r.status_code == 400

    client.patch(f"/api/library/actors/{actor.id}/global", json={"is_global": True})
    r = client.put(
        f"/api/shots/{shot.id}/materials",
        json={"materials": [{"role": "actor", "asset_id": actor.id}]},
    )
    assert r.status_code == 200
    refs = r.json()["refs"]
    assert refs[0]["asset_id"] == actor.id
    assert refs[0]["role"] == "actor"


def test_unpublish_reports_external_refs(client):
    alpha = create_project("Alpha", "First film")
    beta = create_project("Beta", "Second film")
    actor = make_actor("Hero", alpha.id)
    shot = make_shot(beta.id, "sht_beta")
    client.patch(f"/api/library/actors/{actor.id}/global", json={"is_global": True})
    client.put(
        f"/api/shots/{shot.id}/materials",
        json={"materials": [{"role": "actor", "asset_id": actor.id}]},
    )

    r = client.patch(f"/api/library/actors/{actor.id}/global", json={"is_global": False})
    assert r.status_code == 200
    assert r.json()["external_project_ids"] == [beta.id]


def test_unassigned_pool_actor_can_be_published(client):
    alpha = create_project("Alpha", "First film")
    actor = make_actor("Wanderer", None)
    r = client.patch(f"/api/library/actors/{actor.id}/global", json={"is_global": True})
    assert r.status_code == 200
    r = client.get(f"/api/library?kind=actors&project_id={alpha.id}")
    assert actor.id in [x["id"] for x in r.json()]
