"""
Tests for task links. Uses an isolated temporary database file.
"""

import json
import os
import sys
import tempfile

_tmp_dir = tempfile.mkdtemp()
os.environ["KLUKVA_DB_PATH"] = os.path.join(_tmp_dir, "klukva_test_links.json")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from backend.db import db, DEFAULT_DB, _lock, JSONDatabase  # noqa: E402


@pytest.fixture()
def client():
    assert db.file_path == os.environ["KLUKVA_DB_PATH"]
    with _lock:
        db._atomic_write(json.loads(json.dumps(DEFAULT_DB)))
    c = TestClient(app)
    token = c.post("/api/auth/register", json={"username": "alice", "password": "pwd123"}).json()["token"]
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def mk(c, title):
    return c.post("/api/tasks", json={"title": title}).json()["id"]


def link(c, a, b, t, d="outward"):
    return c.post(f"/api/tasks/{a}/links", json={"type": t, "target_id": b, "direction": d})


def test_crud_and_comments(client):
    a, b = mk(client, "A"), mk(client, "B")
    r = link(client, a, b, "blocks")
    assert r.status_code == 201
    la = client.get(f"/api/tasks/{a}/links").json()
    lb = client.get(f"/api/tasks/{b}/links").json()
    assert la[0]["label"] == "Блокирует" and lb[0]["label"] == "Заблокирована"
    assert any("добавил связь" in c["text"] for c in client.get(f"/api/tasks/{b}/comments").json())
    assert client.delete(f"/api/tasks/{b}/links/{la[0]['id']}").status_code == 200
    assert client.get(f"/api/tasks/{a}/links").json() == []
    assert any("удалил связь" in c["text"] for c in client.get(f"/api/tasks/{a}/comments").json())


def test_validation(client):
    a, b, c = mk(client, "A"), mk(client, "B"), mk(client, "C")
    assert link(client, a, a, "relates").status_code == 400
    assert link(client, a, 999, "relates").status_code == 404
    assert link(client, a, b, "relates").status_code == 201
    assert link(client, b, a, "relates").status_code == 400  # duplicate (symmetric)
    assert link(client, a, b, "nope").status_code == 400
    # single parent
    assert link(client, a, c, "parent").status_code == 201
    assert link(client, b, c, "parent").status_code == 400
    # inward direction: c is subtask of b -> already has parent
    assert link(client, c, b, "parent", "inward").status_code == 400
    # cycles
    assert link(client, a, b, "blocks").status_code == 201
    assert link(client, b, c, "blocks").status_code == 201
    assert link(client, c, a, "blocks").status_code == 400
    assert link(client, c, a, "parent").status_code == 400


def test_is_blocked(client):
    a, b = mk(client, "A"), mk(client, "B")
    link(client, a, b, "blocks")
    tb = client.get(f"/api/tasks/{b}").json()
    assert tb["is_blocked"] is True and tb["links_count"] == 1
    client.patch(f"/api/tasks/{a}", json={"status": "Реализовано частично"})
    assert client.get(f"/api/tasks/{b}").json()["is_blocked"] is False
    listed = {t["id"]: t for t in client.get("/api/tasks").json()}
    assert listed[a]["links_count"] == 1


def test_split_partial_creates_parent_link(client):
    a = mk(client, "A")
    r = client.post(f"/api/tasks/{a}/split-partial", json={"title": "rest"})
    new_id = r.json()["backlog_task"]["id"]
    links = client.get(f"/api/tasks/{new_id}/links").json()
    assert len(links) == 1 and links[0]["label"] == "Подзадача" and links[0]["other_task"]["id"] == a


def test_migration_from_parent_task_id():
    path = os.path.join(_tmp_dir, "legacy.json")
    legacy = json.loads(json.dumps(DEFAULT_DB))
    legacy["tasks"] = [
        {"id": 1, "key": "KLUK-1", "title": "P", "status": "Бэклог", "parent_task_id": None},
        {"id": 2, "key": "KLUK-2", "title": "C", "status": "Бэклог", "parent_task_id": 1},
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    ldb = JSONDatabase(path)
    links = ldb.get_links(2)
    assert len(links) == 1 and links[0]["type"] == "parent" and links[0]["direction"] == "inward"

