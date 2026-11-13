"""
Comprehensive tests for user profiles, JWT & trusted devices, TOTP 2FA, PAT & MCP,
RBAC, notifications, activity history, analytics, and task subtypes/clusters.
"""

import json
import os
import struct
import hashlib
import hmac
import base64
import time

import pytest
from fastapi.testclient import TestClient

from backend.db import DEFAULT_DB, _lock, db


def _totp_code(secret: str) -> str:
    s = secret.strip().upper()
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    msg = struct.pack(">Q", int(time.time() // 30))
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    num = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{num:06d}"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from main import app

    db_path = str(tmp_path / "test_platform_db.json")
    monkeypatch.setattr(db, "file_path", db_path)
    with _lock:
        db._atomic_write(json.loads(json.dumps(DEFAULT_DB)))

    att_dir = str(tmp_path / "att")
    av_dir = os.path.join(att_dir, "avatars")
    monkeypatch.setattr("backend.db.ATTACHMENTS_DIR", att_dir)
    monkeypatch.setattr("backend.db.AVATARS_DIR", av_dir)
    monkeypatch.setattr("backend.routes.ATTACHMENTS_DIR", att_dir)
    monkeypatch.setattr("backend.routes.AVATARS_DIR", av_dir)

    c = TestClient(app)
    return c


def _register(c: TestClient, username: str, password: str = "pass123", display_name: str = None, trust_device: bool = False):
    res = c.post("/api/auth/register", json={
        "username": username,
        "password": password,
        "display_name": display_name or username.title(),
        "trust_device": trust_device,
    })
    assert res.status_code == 200, res.text
    return res.json()


def test_jwt_trusted_devices_and_privacy(client):
    reg = _register(client, "alice", trust_device=True)
    token_alice = reg["token"]
    assert reg["user"]["role"] == "admin"
    assert reg["user"]["login_count"] == 1
    assert reg["trusted_device"] is not None
    dev_id = reg["trusted_device"]["id"]

    reg_bob = _register(client, "bob")
    assert reg_bob["user"]["role"] == "member"

    # Alice views her own trusted devices
    h_alice = {"Authorization": f"Bearer {token_alice}"}
    prof = client.get("/api/profile", headers=h_alice)
    assert prof.status_code == 200
    assert len(prof.json()["trusted_devices"]) == 1
    assert prof.json()["trusted_devices"][0]["is_current"] is True

    # Bob views Alice's public profile -> must NOT expose trusted_devices, pat_tokens, or totp_secret
    h_bob = {"Authorization": f"Bearer {reg_bob['token']}"}
    pub_alice = client.get("/api/users/alice/profile", headers=h_bob)
    assert pub_alice.status_code == 200
    pub_data = pub_alice.json()
    assert "trusted_devices" not in pub_data
    assert "pat_tokens" not in pub_data
    assert "totp_secret" not in pub_data["user"]

    # Alice revokes her trusted device -> her device-bound JWT immediately stops working
    rev = client.delete(f"/api/profile/trusted-devices/{dev_id}", headers=h_alice)
    assert rev.status_code == 200
    assert client.get("/api/auth/me", headers=h_alice).status_code == 401


def test_profile_edit_avatar_password_and_totp(client):
    reg = _register(client, "alice", password="old_password")
    headers = {"Authorization": f"Bearer {reg['token']}"}

    # Edit ФИО
    p_res = client.patch("/api/profile", json={"display_name": "Алиса Иванова"}, headers=headers)
    assert p_res.status_code == 200
    assert p_res.json()["display_name"] == "Алиса Иванова"

    # Upload & fetch avatar
    png_bytes = b"\x89PNG\r\n\x1a\nfake_png_data"
    av_res = client.post("/api/profile/avatar?filename=ava.png", content=png_bytes,
                         headers={**headers, "Content-Type": "image/png"})
    assert av_res.status_code == 200
    assert av_res.json()["avatar_url"] is not None
    get_av = client.get("/api/users/alice/avatar")
    assert get_av.status_code == 200
    assert get_av.content == png_bytes

    # Change password
    pw_res = client.post("/api/profile/password", json={
        "current_password": "old_password",
        "new_password": "new_password"
    }, headers=headers)
    assert pw_res.status_code == 200

    # Setup & enable TOTP
    setup = client.post("/api/profile/totp/setup", headers=headers).json()
    assert "qr_svg" in setup and "<svg" in setup["qr_svg"]
    secret = setup["secret"]
    code = _totp_code(secret)
    en = client.post("/api/profile/totp/enable", json={"code": code}, headers=headers)
    assert en.status_code == 200 and en.json()["totp_enabled"] is True

    # Login with new password -> requires_totp
    login1 = client.post("/api/auth/login", json={"username": "alice", "password": "new_password", "trust_device": True})
    assert login1.status_code == 200
    assert login1.json()["requires_totp"] is True
    challenge = login1.json()["challenge_token"]

    # Complete TOTP login
    login2 = client.post("/api/auth/login/totp", json={"challenge_token": challenge, "code": _totp_code(secret)})
    assert login2.status_code == 200
    assert "token" in login2.json()
    assert login2.json()["user"]["login_count"] == 2

    # Disable TOTP
    dis = client.post("/api/profile/totp/disable", json={"password": "new_password"}, headers=headers)
    assert dis.status_code == 200 and dis.json()["totp_enabled"] is False


def test_rbac_pat_and_mcp(client):
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    h_alice = {"Authorization": f"Bearer {alice['token']}"}
    h_bob = {"Authorization": f"Bearer {bob['token']}"}

    # Member cannot create sprint or change roles
    assert client.post("/api/sprints", json={"name": "S1"}, headers=h_bob).status_code == 403
    assert client.patch(f"/api/users/{alice['user']['id']}/role", json={"role": "viewer"}, headers=h_bob).status_code == 403

    # Admin changes Bob to viewer
    r_upd = client.patch(f"/api/users/{bob['user']['id']}/role", json={"role": "viewer"}, headers=h_alice)
    assert r_upd.status_code == 200 and r_upd.json()["role"] == "viewer"

    # Viewer cannot create tasks
    assert client.post("/api/tasks", json={"title": "Nope"}, headers=h_bob).status_code == 403

    # Admin creates PAT & uses MCP
    pat_res = client.post("/api/profile/tokens", json={"name": "CI MCP", "expires_days": 30}, headers=h_alice)
    assert pat_res.status_code == 201
    pat_token = pat_res.json()["token"]
    assert pat_token.startswith("klk_")
    h_pat = {"Authorization": f"Bearer {pat_token}"}

    # MCP initialize & tools/list & tools/call
    init_res = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, headers=h_pat)
    assert init_res.status_code == 200
    assert init_res.json()["result"]["serverInfo"]["name"] == "klukva-mcp"

    list_res = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=h_pat)
    assert list_res.status_code == 200
    tool_names = [t["name"] for t in list_res.json()["result"]["tools"]]
    assert "create_task" in tool_names and "get_analytics" in tool_names

    call_res = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "create_task",
            "arguments": {"title": "MCP Bug", "task_type": "Ошибка", "cluster": "Сириус", "story_points": 3}
        }
    }, headers=h_pat)
    assert call_res.status_code == 200
    assert call_res.json()["result"]["isError"] is False
    created_task = json.loads(call_res.json()["result"]["content"][0]["text"])
    assert created_task["task_type"] == "Ошибка"
    assert created_task["cluster"] == "Сириус"


def test_task_types_clusters_notifications_activity_analytics(client):
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    h_alice = {"Authorization": f"Bearer {alice['token']}"}
    h_bob = {"Authorization": f"Bearer {bob['token']}"}

    # Create tasks of all subtypes & clusters
    t1 = client.post("/api/tasks", json={
        "title": "New Feature",
        "task_type": "Нововведение",
        "cluster": "Эпик",
        "assignee": "bob",
        "story_points": 5
    }, headers=h_alice).json()
    assert t1["task_type"] == "Нововведение" and t1["cluster"] == "Эпик"

    t2 = client.post("/api/tasks", json={
        "title": "Check PR",
        "task_type": "Ревью",
        "cluster": "Сириус",
        "story_points": 2
    }, headers=h_alice).json()

    # Filter by task_type & cluster
    filtered = client.get("/api/tasks?task_type=Ревью&cluster=Сириус", headers=h_alice).json()
    assert len(filtered) == 1 and filtered[0]["id"] == t2["id"]

    # Bob should have notification about assigned task t1
    bob_notifs = client.get("/api/notifications", headers=h_bob).json()
    assert bob_notifs["unread_count"] >= 1

    # Alice mentions Bob in comment on t2 -> Bob gets mention notification
    client.post(f"/api/tasks/{t2['id']}/comments", json={"text": "Привет @bob проверь"}, headers=h_alice)
    bob_notifs2 = client.get("/api/notifications", headers=h_bob).json()
    assert bob_notifs2["unread_count"] >= 2

    # Bob marks all read
    client.post("/api/notifications/read-all", headers=h_bob)
    assert client.get("/api/notifications", headers=h_bob).json()["unread_count"] == 0

    # Bob finishes t1 -> activity log & analytics updated
    client.patch(f"/api/tasks/{t1['id']}", json={"status": "Завершено"}, headers=h_bob)
    bob_act = client.get("/api/profile/activity", headers=h_bob).json()
    assert bob_act["stats"]["completed_total"] == 1
    assert bob_act["stats"]["completed_sp"] == 5.0

    analytics = client.get("/api/analytics", headers=h_alice).json()
    assert analytics["summary"]["total_tasks"] == 2
    assert analytics["summary"]["done_tasks"] == 1
    assert any(x["label"] == "Эпик" and x["count"] == 1 for x in analytics["by_cluster"])
    assert any(x["label"] == "Нововведение" and x["count"] == 1 for x in analytics["by_type"])


def test_system_user_forced_credentials_and_full_access(tmp_path, monkeypatch):
    from main import app

    db_path = str(tmp_path / "test_sys_db.json")
    monkeypatch.setattr(db, "file_path", db_path)
    with _lock:
        db._atomic_write(json.loads(json.dumps(DEFAULT_DB)))

    att_dir = str(tmp_path / "att_sys")
    av_dir = os.path.join(att_dir, "avatars")
    monkeypatch.setattr("backend.db.ATTACHMENTS_DIR", att_dir)
    monkeypatch.setattr("backend.db.AVATARS_DIR", av_dir)
    monkeypatch.setattr("backend.routes.ATTACHMENTS_DIR", att_dir)
    monkeypatch.setattr("backend.routes.AVATARS_DIR", av_dir)

    with TestClient(app) as c:
        # 1. Lifespan seeded default admin/admin
        login_res = c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        assert login_res.status_code == 200, login_res.text
        data = login_res.json()
        assert data["user"]["is_system"] is True
        assert data["user"]["role"] == "admin"
        assert data["user"]["must_change_credentials"] is True

        old_token = data["token"]
        h_old = {"Authorization": f"Bearer {old_token}"}

        # 2. Onboarding lock: allowed profile/me, blocked tasks/system/mcp
        assert c.get("/api/auth/me", headers=h_old).status_code == 200
        assert c.get("/api/profile", headers=h_old).status_code == 200
        assert c.get("/api/tasks", headers=h_old).status_code == 403
        assert c.get("/api/system/audit", headers=h_old).status_code == 403
        assert c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=h_old).status_code == 403

        # 3. Validation on /api/profile/credentials
        assert c.post("/api/profile/credentials", json={
            "current_password": "wrong", "new_username": "sysroot", "new_password": "StrongPassword1"
        }, headers=h_old).status_code == 400
        assert c.post("/api/profile/credentials", json={
            "current_password": "admin", "new_username": "admin", "new_password": "StrongPassword1"
        }, headers=h_old).status_code == 400
        assert c.post("/api/profile/credentials", json={
            "current_password": "admin", "new_username": "sysroot", "new_password": "admin"
        }, headers=h_old).status_code == 400

        # 4. Change credentials cleanly
        cred_res = c.post("/api/profile/credentials", json={
            "current_password": "admin",
            "new_username": "sysroot",
            "new_password": "StrongPassword1",
        }, headers=h_old)
        assert cred_res.status_code == 200, cred_res.text
        new_token = cred_res.json()["token"]
        assert cred_res.json()["user"]["username"] == "sysroot"
        assert cred_res.json()["user"]["must_change_credentials"] is False
        assert cred_res.json()["user"]["is_system"] is True
        h_sys = {"Authorization": f"Bearer {new_token}"}

        # Old token invalidated and old admin/admin no longer works
        assert c.get("/api/auth/me", headers=h_old).status_code == 401
        assert c.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 401
        assert c.get("/api/tasks", headers=h_sys).status_code == 200

        # Restart ensure_system_admin must NOT recreate admin/admin
        db.ensure_system_admin()
        assert db.get_user_by_username("admin") is None

        # 5. Normal user registers -> gets 'member' role, cannot access system endpoints
        dev = _register(c, "dev", password="devpass123")
        assert dev["user"]["role"] == "member"
        h_dev = {"Authorization": f"Bearer {dev['token']}"}
        assert c.get("/api/system/audit", headers=h_dev).status_code == 403
        assert c.get("/api/system/files", headers=h_dev).status_code == 403

        # Dev creates a task + attachment
        t = c.post("/api/tasks", json={"title": "User Task"}, headers=h_dev).json()
        up = c.post(
            f"/api/tasks/{t['id']}/attachments?filename=secret.txt",
            content=b"top-secret-file",
            headers={**h_dev, "Content-Type": "text/plain"},
        )
        assert up.status_code == 201
        att_id = up.json()["id"]

        # Cannot demote system user
        sys_id = cred_res.json()["user"]["id"]
        c.patch(f"/api/users/{dev['user']['id']}/role", json={"role": "admin"}, headers=h_sys)
        assert c.patch(f"/api/users/{sys_id}/role", json={"role": "member"}, headers=h_dev).status_code == 400

        # System user sees all files, all changes in audit, DB snapshot, and MCP system tools
        files_res = c.get("/api/system/files", headers=h_sys)
        assert files_res.status_code == 200
        assert any(a["id"] == att_id and a["filename"] == "secret.txt" for a in files_res.json()["attachments"])

        # System user can delete dev's attachment
        assert c.delete(f"/api/tasks/{t['id']}/attachments/{att_id}", headers=h_sys).status_code == 200

        audit_res = c.get("/api/system/audit", headers=h_sys)
        assert audit_res.status_code == 200
        actions = {a["action"] for a in audit_res.json()["items"]}
        assert {"auth_login", "credentials_changed", "auth_register", "task_created", "attachment_uploaded", "attachment_deleted"}.issubset(actions)

        snap_res = c.get("/api/system/db-export", headers=h_sys)
        assert snap_res.status_code == 200
        assert len(snap_res.json()["users"]) == 2

        mcp_list = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=h_sys)
        tool_names = {tool["name"] for tool in mcp_list.json()["result"]["tools"]}
        assert {"get_audit_log", "list_all_files"}.issubset(tool_names)

        mcp_audit = c.post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "get_audit_log", "arguments": {"limit": 10}}
        }, headers=h_sys)
        assert mcp_audit.json()["result"]["isError"] is False


def test_sirius_epic_task_hierarchy(client):
    alice = _register(client, "alice")
    h = {"Authorization": f"Bearer {alice['token']}"}

    # 1. Create Sirius -> Epics -> Child Tasks
    sirius_res = client.post("/api/tasks", json={"title": "Auth & Security Program", "task_type": "Сириус"}, headers=h)
    assert sirius_res.status_code == 201
    sirius = sirius_res.json()
    assert sirius["task_type"] == "Сириус"

    epic1_res = client.post("/api/tasks", json={
        "title": "JWT & Sessions",
        "task_type": "Эпик",
        "sirius_id": sirius["id"]
    }, headers=h)
    assert epic1_res.status_code == 201
    epic1 = epic1_res.json()
    assert epic1["sirius_id"] == sirius["id"]
    assert epic1["sirius_key"] == sirius["key"]

    epic2_res = client.post("/api/tasks", json={"title": "Audit UI", "task_type": "Эпик"}, headers=h)
    assert epic2_res.status_code == 201
    epic2 = epic2_res.json()

    t1 = client.post("/api/tasks", json={
        "title": "Add JWT tokens",
        "task_type": "Нововведение",
        "epic_id": epic1["id"],
        "story_points": 5
    }, headers=h).json()
    assert t1["epic_id"] == epic1["id"]
    assert t1["epic_key"] == epic1["key"]

    t2 = client.post("/api/tasks", json={
        "title": "Fix refresh bug",
        "task_type": "Ошибка",
        "epic_id": epic1["id"],
        "story_points": 3
    }, headers=h).json()

    # Invalid hierarchy bindings must fail cleanly with 400
    assert client.post("/api/tasks", json={"title": "Bad", "task_type": "Задача", "epic_id": sirius["id"]}, headers=h).status_code == 400
    assert client.post("/api/tasks", json={"title": "Bad2", "task_type": "Задача", "epic_id": t1["id"]}, headers=h).status_code == 400
    assert client.patch(f"/api/tasks/{epic1['id']}", json={"sirius_id": t1["id"]}, headers=h).status_code == 400
    assert client.patch(f"/api/tasks/{epic1['id']}", json={"sirius_id": epic1["id"]}, headers=h).status_code == 400

    # Filtering by epic_id and sirius_id
    by_epic = client.get(f"/api/tasks?epic_id={epic1['id']}", headers=h).json()
    assert {x["id"] for x in by_epic} == {t1["id"], t2["id"]}

    by_sirius = client.get(f"/api/tasks?sirius_id={sirius['id']}", headers=h).json()
    assert {x["id"] for x in by_sirius} == {epic1["id"], t1["id"], t2["id"]}

    # Mark t1 done and check detail & analytics progress
    assert client.patch(f"/api/tasks/{t1['id']}", json={"status": "Завершено"}, headers=h).status_code == 200

    epic_detail = client.get(f"/api/tasks/{epic1['id']}", headers=h).json()
    assert len(epic_detail["epic_tasks"]) == 2
    assert epic_detail["children_total"] == 2
    assert epic_detail["children_done"] == 1

    sirius_detail = client.get(f"/api/tasks/{sirius['id']}", headers=h).json()
    assert len(sirius_detail["sirius_epics"]) == 1
    assert sirius_detail["epics_total"] == 1
    assert sirius_detail["children_total"] == 2
    assert sirius_detail["children_done"] == 1

    analytics = client.get("/api/analytics", headers=h).json()
    ep_prog = next(e for e in analytics["epics"] if e["id"] == epic1["id"])
    assert ep_prog["total_tasks"] == 2 and ep_prog["done_tasks"] == 1
    assert ep_prog["total_sp"] == 8.0 and ep_prog["done_sp"] == 5.0
    sr_prog = next(s for s in analytics["siriuses"] if s["id"] == sirius["id"])
    assert sr_prog["epics_count"] == 1
    assert sr_prog["total_tasks"] == 2 and sr_prog["done_tasks"] == 1

    # MCP hierarchy support: attach epic2 to sirius & list tasks by sirius_id
    pat = client.post("/api/profile/tokens", json={"name": "mcp"}, headers=h).json()["token"]
    h_pat = {"Authorization": f"Bearer {pat}"}
    mcp_upd = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "update_task", "arguments": {"task_id": epic2["id"], "sirius_id": sirius["id"]}}
    }, headers=h_pat)
    assert mcp_upd.json()["result"]["isError"] is False
    mcp_get = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 11, "method": "tools/call",
        "params": {"name": "get_task", "arguments": {"task_id": sirius["id"]}}
    }, headers=h_pat)
    sirius_mcp = json.loads(mcp_get.json()["result"]["content"][0]["text"])
    assert len(sirius_mcp["sirius_epics"]) == 2
