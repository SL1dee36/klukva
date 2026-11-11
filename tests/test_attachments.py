import json
import os
import sys
import pytest
from fastapi.testclient import TestClient

from backend.db import db, DEFAULT_DB, _lock


@pytest.fixture
def client(tmp_path, monkeypatch):
    from main import app

    with _lock:
        db._atomic_write(json.loads(json.dumps(DEFAULT_DB)))

    test_att_dir = str(tmp_path / "test_attachments")
    monkeypatch.setattr("backend.routes.ATTACHMENTS_DIR", test_att_dir)
    monkeypatch.setattr("backend.db.ATTACHMENTS_DIR", test_att_dir)

    c = TestClient(app)
    # Register & login
    reg_res = c.post("/api/auth/register", json={"username": "bob", "password": "pwd123", "display_name": "Bob"})
    token = reg_res.json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c, token


def test_attachment_upload_download_delete(client):
    c, token = client
    # Create task
    t_res = c.post("/api/tasks", json={"title": "Test Attachments Task"})
    task_id = t_res.json()["id"]

    # 1. Upload small file
    content = b"Hello, Klukva attachment!"
    up_res = c.post(
        f"/api/tasks/{task_id}/attachments?filename=note.txt",
        content=content,
        headers={"Content-Type": "text/plain"}
    )
    assert up_res.status_code == 201
    att = up_res.json()
    assert att["filename"] == "note.txt"
    assert att["size"] == len(content)
    att_id = att["id"]

    # 2. List attachments
    list_res = c.get(f"/api/tasks/{task_id}/attachments")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    # 3. Download inline
    dl_res = c.get(f"/api/tasks/{task_id}/attachments/{att_id}/file?token={token}")
    assert dl_res.status_code == 200
    assert dl_res.content == content
    assert dl_res.headers.get("content-disposition") == 'inline; filename="note.txt"'

    # 4. Download attachment
    dl_res2 = c.get(f"/api/tasks/{task_id}/attachments/{att_id}/file?download=true&token={token}")
    assert dl_res2.status_code == 200
    assert dl_res2.headers.get("content-disposition") == 'attachment; filename="note.txt"'

    # 5. Check size limit (> 20MB)
    too_big = b"X" * (20 * 1024 * 1024 + 1)
    big_res = c.post(
        f"/api/tasks/{task_id}/attachments?filename=big.bin",
        content=too_big,
        headers={"Content-Length": str(len(too_big)), "Content-Type": "application/octet-stream"}
    )
    assert big_res.status_code == 413

    # 6. Delete attachment
    del_res = c.delete(f"/api/tasks/{task_id}/attachments/{att_id}")
    assert del_res.status_code == 200
    assert c.get(f"/api/tasks/{task_id}/attachments").json() == []
