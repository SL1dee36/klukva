"""
JSON Database module for Klukva task tracker.
Thread-safe, atomic file writes to prevent any data corruption.
"""

import json
import os
import secrets
import tempfile
import threading
import re
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

def get_db_file_path() -> str:
    if os.environ.get("KLUKVA_DB_PATH"):
        return os.path.abspath(os.environ["KLUKVA_DB_PATH"])

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        parent_dir = os.path.dirname(exe_dir)
        candidate = os.path.join(parent_dir, "klukva_db.json")
        if os.path.exists(candidate) or os.path.exists(os.path.join(parent_dir, ".git")):
            return candidate
        return os.path.join(exe_dir, "klukva_db.json")

    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "klukva_db.json"))

DB_FILE_PATH = get_db_file_path()

_lock = threading.Lock()

DEFAULT_DB: Dict[str, Any] = {
    "users": [],
    "tasks": [],
    "comments": [],
    "sprints": [],
    "attachments": [],
    "notifications": [],
    "activities": [],
    "revoked_jtis": [],
    "settings": {},
    "counters": {
        "user_id": 0,
        "task_id": 0,
        "comment_id": 0,
        "sprint_id": 0,
        "attachment_id": 0,
        "notification_id": 0,
        "activity_id": 0,
    }
}

VALID_STATUSES = [
    "Бэклог",
    "В работе",
    "Завершено",
    "Не реализовано",
    "Реализовано частично"
]

FINAL_STATUSES = {"Завершено", "Не реализовано", "Реализовано частично"}

VALID_TASK_TYPES = [
    "Задача",
    "Нововведение",
    "Ошибка",
    "Тестирование",
    "Ревью",
    "Исследование",
    "Эпик",
    "Сириус",
]

CONTAINER_TASK_TYPES = {"Эпик", "Сириус"}

VALID_CLUSTERS = ["", "Эпик", "Сириус"]

VALID_ROLES = ["admin", "manager", "member", "viewer"]
ROLE_HIERARCHY = {"viewer": 0, "member": 1, "manager": 2, "admin": 3}

# type -> (label for source, label for target)
LINK_LABELS = {
    "relates": ("Связана с", "Связана с"),
    "blocks": ("Блокирует", "Заблокирована"),
    "parent": ("Родитель для", "Подзадача"),
}


class JSONDatabase:
    def __init__(self, file_path: str = DB_FILE_PATH):
        self.file_path = file_path
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not os.path.exists(self.file_path):
            with _lock:
                if not os.path.exists(self.file_path):
                    self._atomic_write(DEFAULT_DB)

    def _read_data(self) -> Dict[str, Any]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return json.loads(json.dumps(DEFAULT_DB))

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        dir_name = os.path.dirname(self.file_path)
        os.makedirs(dir_name, exist_ok=True)
        # Write to temporary file in the same directory for atomic replace
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
            json.dump(data, tf, ensure_ascii=False, indent=2)
            temp_name = tf.name
        os.replace(temp_name, self.file_path)

    # ------------------ SETTINGS / JWT ------------------
    def get_or_create_jwt_secret(self) -> str:
        with _lock:
            data = self._read_data()
            settings = data.setdefault("settings", {})
            secret = settings.get("jwt_secret")
            if not secret:
                secret = secrets.token_hex(32)
                settings["jwt_secret"] = secret
                self._atomic_write(data)
            return secret

    def revoke_jti(self, jti: str, exp: int) -> None:
        if not jti:
            return
        with _lock:
            data = self._read_data()
            now_ts = int(datetime.utcnow().timestamp())
            revoked = [r for r in data.get("revoked_jtis", []) if r.get("exp", 0) > now_ts]
            if not any(r.get("jti") == jti for r in revoked):
                revoked.append({"jti": jti, "exp": exp})
            data["revoked_jtis"] = revoked
            self._atomic_write(data)

    def is_jti_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        with _lock:
            data = self._read_data()
            return any(r.get("jti") == jti for r in data.get("revoked_jtis", []))

    # ------------------ USERS ------------------
    @staticmethod
    def _effective_role(data: Dict[str, Any], user: Dict[str, Any]) -> str:
        role = user.get("role")
        if role in VALID_ROLES:
            return role
        users = data.get("users", [])
        if users and users[0]["id"] == user["id"] and not any(u.get("role") == "admin" for u in users):
            return "admin"
        return "member"

    @classmethod
    def public_user(cls, data: Dict[str, Any], u: Dict[str, Any], include_private: bool = False) -> Dict[str, Any]:
        role = cls._effective_role(data, u)
        avatar = u.get("avatar")
        res = {
            "id": u["id"],
            "username": u["username"],
            "display_name": u.get("display_name", u["username"]),
            "role": role,
            "is_system": bool(u.get("is_system", False)),
            "avatar_url": f"/api/users/{u['username']}/avatar?v={avatar}" if avatar else None,
            "created_at": u.get("created_at"),
            "last_login_at": u.get("last_login_at"),
            "login_count": u.get("login_count", 0),
        }
        if include_private:
            res["totp_enabled"] = bool(u.get("totp_enabled", False))
            res["must_change_credentials"] = bool(u.get("must_change_credentials", False))
        return res

    def get_users(self) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            return [self.public_user(data, u) for u in data.get("users", [])]

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for u in data.get("users", []):
                if u["username"].lower() == username.lower():
                    u["role"] = self._effective_role(data, u)
                    return u
            return None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for u in data.get("users", []):
                if u["id"] == user_id:
                    u["role"] = self._effective_role(data, u)
                    return u
            return None

    def create_user(self, username: str, password_hash: str, display_name: str, role: Optional[str] = None) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            for u in data.get("users", []):
                if u["username"].lower() == username.lower():
                    raise ValueError(f"Пользователь '{username}' уже существует")

            data["counters"]["user_id"] += 1
            user_id = data["counters"]["user_id"]
            assigned_role = role if role in VALID_ROLES else ("admin" if len(data.get("users", [])) == 0 else "member")
            new_user = {
                "id": user_id,
                "username": username,
                "password_hash": password_hash,
                "display_name": display_name or username,
                "role": assigned_role,
                "is_system": False,
                "must_change_credentials": False,
                "avatar": None,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "last_login_at": None,
                "login_count": 0,
                "totp_enabled": False,
                "totp_secret": None,
                "totp_pending_secret": None,
                "trusted_devices": [],
                "pat_tokens": [],
            }
            data["users"].append(new_user)
            self._atomic_write(data)
            return self.public_user(data, new_user, include_private=True)

    def ensure_system_admin(self) -> Dict[str, Any]:
        """Ensure a dedicated system superuser exists (default admin/admin requiring first-login credential change)."""
        from backend.auth import hash_password

        with _lock:
            data = self._read_data()
            users = data.setdefault("users", [])
            existing_sys = next((u for u in users if u.get("is_system")), None)
            if existing_sys:
                return existing_sys

            existing_admin = next((u for u in users if u["username"].lower() == "admin"), None)
            if existing_admin:
                existing_admin["is_system"] = True
                existing_admin["role"] = "admin"
                existing_admin.setdefault("must_change_credentials", False)
                self._atomic_write(data)
                return existing_admin

            counters = data.setdefault("counters", {})
            counters["user_id"] = counters.get("user_id", 0) + 1
            user_id = counters["user_id"]
            sys_user = {
                "id": user_id,
                "username": "admin",
                "password_hash": hash_password("admin"),
                "display_name": "Системный администратор",
                "role": "admin",
                "is_system": True,
                "must_change_credentials": True,
                "avatar": None,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "last_login_at": None,
                "login_count": 0,
                "totp_enabled": False,
                "totp_secret": None,
                "totp_pending_secret": None,
                "trusted_devices": [],
                "pat_tokens": [],
            }
            users.insert(0, sys_user)
            self._atomic_write(data)
            return sys_user

    def record_login(self, user_id: int, device_info: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for u in data.get("users", []):
                if u["id"] == user_id:
                    now = datetime.utcnow().isoformat() + "Z"
                    u["last_login_at"] = now
                    u["login_count"] = int(u.get("login_count", 0)) + 1
                    u["role"] = self._effective_role(data, u)
                    if device_info:
                        devices = u.setdefault("trusted_devices", [])
                        devices.append(device_info)
                        # Keep up to 20 most recent trusted devices
                        if len(devices) > 20:
                            u["trusted_devices"] = devices[-20:]
                    self._atomic_write(data)
                    return self.public_user(data, u, include_private=True)
            return None

    def update_user_profile(
        self,
        user_id: int,
        display_name: Optional[str] = None,
        password_hash: Optional[str] = None,
        avatar: Any = ...,
    ) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for u in data.get("users", []):
                if u["id"] == user_id:
                    if display_name is not None:
                        u["display_name"] = display_name.strip() or u["username"]
                    if password_hash is not None:
                        u["password_hash"] = password_hash
                    if avatar is not ...:
                        u["avatar"] = avatar
                    self._atomic_write(data)
                    return self.public_user(data, u, include_private=True)
            return None

    def update_user_role(self, user_id: int, role: str) -> Optional[Dict[str, Any]]:
        if role not in VALID_ROLES:
            raise ValueError("Недопустимая роль")
        with _lock:
            data = self._read_data()
            users = data.get("users", [])
            target = next((u for u in users if u["id"] == user_id), None)
            if not target:
                return None
            if target.get("is_system") and role != "admin":
                raise ValueError("Нельзя понизить роль системного пользователя")
            current_role = self._effective_role(data, target)
            if current_role == "admin" and role != "admin":
                admin_count = sum(1 for u in users if self._effective_role(data, u) == "admin")
                if admin_count <= 1:
                    raise ValueError("Нельзя снять роль администратора с единственного администратора")
            target["role"] = role
            self._atomic_write(data)
            return self.public_user(data, target)

    def update_user_credentials(
        self,
        user_id: int,
        new_username: str,
        new_password_hash: str,
    ) -> Optional[Dict[str, Any]]:
        """Update username + password atomically and cascade username across all collections."""
        clean_username = new_username.strip()
        if not re.match(r"^[a-zA-Z0-9_\-]{2,32}$", clean_username):
            raise ValueError("Логин должен содержать 2-32 символа (латиница, цифры, _ или -)")
        with _lock:
            data = self._read_data()
            users = data.get("users", [])
            target = next((u for u in users if u["id"] == user_id), None)
            if not target:
                return None
            if target.get("is_system") and clean_username.lower() == "admin":
                raise ValueError("Системному пользователю необходимо задать логин, отличный от 'admin'")
            for u in users:
                if u["id"] != user_id and u["username"].lower() == clean_username.lower():
                    raise ValueError(f"Логин '{clean_username}' уже занят")

            old_username = target["username"]
            target["username"] = clean_username
            target["password_hash"] = new_password_hash
            target["must_change_credentials"] = False

            if old_username != clean_username:
                old_low = old_username.lower()
                for t in data.get("tasks", []):
                    if (t.get("assignee") or "").lower() == old_low:
                        t["assignee"] = clean_username
                    if (t.get("created_by") or "").lower() == old_low:
                        t["created_by"] = clean_username
                for c in data.get("comments", []):
                    if (c.get("author") or "").lower() == old_low:
                        c["author"] = clean_username
                for s in data.get("sprints", []):
                    if (s.get("created_by") or "").lower() == old_low:
                        s["created_by"] = clean_username
                for l in data.get("links", []):
                    if (l.get("created_by") or "").lower() == old_low:
                        l["created_by"] = clean_username
                for a in data.get("attachments", []):
                    if (a.get("uploaded_by") or "").lower() == old_low:
                        a["uploaded_by"] = clean_username
                for n in data.get("notifications", []):
                    if (n.get("username") or "").lower() == old_low:
                        n["username"] = clean_username
                    if (n.get("actor") or "").lower() == old_low:
                        n["actor"] = clean_username
                for act in data.get("activities", []):
                    if (act.get("username") or "").lower() == old_low:
                        act["username"] = clean_username

            counters = data.setdefault("counters", {})
            counters["activity_id"] = counters.get("activity_id", 0) + 1
            data.setdefault("activities", []).append({
                "id": counters["activity_id"],
                "username": clean_username,
                "action": "credentials_changed",
                "task_id": None,
                "task_key": None,
                "task_title": None,
                "details": f"Изменены учётные данные ({old_username} -> {clean_username})",
                "created_at": datetime.utcnow().isoformat() + "Z",
            })

            self._atomic_write(data)
            return self.public_user(data, target, include_private=True)

    def clear_user_trusted_devices(self, user_id: int) -> int:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return 0
            count = len(u.get("trusted_devices", []))
            u["trusted_devices"] = []
            if count:
                self._atomic_write(data)
            return count

    def get_system_users_summary(self) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            out = []
            for u in data.get("users", []):
                pub = self.public_user(data, u, include_private=True)
                pub["trusted_devices_count"] = len(u.get("trusted_devices", []))
                pub["pat_count"] = len(u.get("pat_tokens", []))
                out.append(pub)
            return out

    def export_snapshot(self) -> Dict[str, Any]:
        with _lock:
            return self._read_data()

    # ------------------ TRUSTED DEVICES ------------------
    def get_trusted_devices(self, user_id: int) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return []
            now_iso = datetime.utcnow().isoformat() + "Z"
            return [d for d in u.get("trusted_devices", []) if d.get("expires_at", now_iso) >= now_iso]

    def is_trusted_device_active(self, user_id: int, device_id: str) -> bool:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return False
            now_iso = datetime.utcnow().isoformat() + "Z"
            for d in u.get("trusted_devices", []):
                if d.get("id") == device_id and d.get("expires_at", now_iso) >= now_iso:
                    return True
            return False

    def touch_trusted_device(self, user_id: int, device_id: str) -> None:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return
            for d in u.get("trusted_devices", []):
                if d.get("id") == device_id:
                    d["last_used_at"] = datetime.utcnow().isoformat() + "Z"
                    self._atomic_write(data)
                    return

    def remove_trusted_device(self, user_id: int, device_id: str) -> bool:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return False
            devices = u.get("trusted_devices", [])
            new_devices = [d for d in devices if d.get("id") != device_id]
            if len(new_devices) == len(devices):
                return False
            u["trusted_devices"] = new_devices
            self._atomic_write(data)
            return True

    # ------------------ TOTP ------------------
    def set_totp_pending(self, user_id: int, secret: str) -> bool:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return False
            u["totp_pending_secret"] = secret
            self._atomic_write(data)
            return True

    def enable_totp(self, user_id: int, secret: str) -> bool:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return False
            u["totp_secret"] = secret
            u["totp_pending_secret"] = None
            u["totp_enabled"] = True
            self._atomic_write(data)
            return True

    def disable_totp(self, user_id: int) -> bool:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return False
            u["totp_secret"] = None
            u["totp_pending_secret"] = None
            u["totp_enabled"] = False
            self._atomic_write(data)
            return True

    # ------------------ PERSONAL ACCESS TOKENS ------------------
    def get_pats(self, user_id: int) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return []
            return [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "prefix": p["prefix"],
                    "created_at": p["created_at"],
                    "last_used_at": p.get("last_used_at"),
                    "expires_at": p.get("expires_at"),
                }
                for p in u.get("pat_tokens", [])
            ]

    def create_pat(self, user_id: int, name: str, prefix: str, token_hash: str, expires_at: Optional[str]) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                raise ValueError("Пользователь не найден")
            pat = {
                "id": secrets.token_hex(8),
                "name": name.strip(),
                "prefix": prefix,
                "token_hash": token_hash,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "last_used_at": None,
                "expires_at": expires_at,
            }
            u.setdefault("pat_tokens", []).append(pat)
            self._atomic_write(data)
            return {k: v for k, v in pat.items() if k != "token_hash"}

    def delete_pat(self, user_id: int, pat_id: str) -> bool:
        with _lock:
            data = self._read_data()
            u = next((u for u in data.get("users", []) if u["id"] == user_id), None)
            if not u:
                return False
            pats = u.get("pat_tokens", [])
            new_pats = [p for p in pats if p["id"] != pat_id]
            if len(new_pats) == len(pats):
                return False
            u["pat_tokens"] = new_pats
            self._atomic_write(data)
            return True

    def find_user_by_pat_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            now_iso = datetime.utcnow().isoformat() + "Z"
            for u in data.get("users", []):
                for p in u.get("pat_tokens", []):
                    if p.get("token_hash") == token_hash:
                        exp = p.get("expires_at")
                        if exp and exp < now_iso:
                            return None
                        p["last_used_at"] = now_iso
                        u["role"] = self._effective_role(data, u)
                        self._atomic_write(data)
                        return u
            return None

    # ------------------ TASKS ------------------
    def get_tasks(
        self,
        status: Optional[str] = None,
        story_points: Optional[float] = None,
        min_sp: Optional[float] = None,
        max_sp: Optional[float] = None,
        assignee: Optional[str] = None,
        search: Optional[str] = None,
        exclude_backlog: bool = False,
        in_sprint: Optional[bool] = None,
        task_type: Optional[str] = None,
        cluster: Optional[str] = None,
        epic_id: Optional[int] = None,
        sirius_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            tasks = data.get("tasks", [])

            sirius_epic_ids = set()
            if sirius_id is not None:
                sirius_epic_ids = {
                    t["id"] for t in tasks
                    if t.get("task_type") == "Эпик" and t.get("sirius_id") == sirius_id
                }

            result = []
            for t in tasks:
                if status and t.get("status") != status:
                    continue
                if exclude_backlog and t.get("status") == "Бэклог":
                    continue
                if in_sprint is not None and bool(t.get("in_sprint", False)) != in_sprint:
                    continue
                if task_type and (t.get("task_type") or "Задача") != task_type:
                    continue
                if cluster is not None:
                    if cluster == "none" and (t.get("cluster") or ""):
                        continue
                    elif cluster != "none" and cluster != "" and (t.get("cluster") or "") != cluster:
                        continue
                if epic_id is not None and t.get("epic_id") != epic_id:
                    continue
                if sirius_id is not None:
                    if t.get("sirius_id") != sirius_id and t.get("epic_id") not in sirius_epic_ids:
                        continue
                if story_points is not None and t.get("story_points") != story_points:
                    continue
                if min_sp is not None and (t.get("story_points") is None or t.get("story_points") < min_sp):
                    continue
                if max_sp is not None and (t.get("story_points") is not None and t.get("story_points") > max_sp):
                    continue
                if assignee is not None:
                    t_assignee = t.get("assignee") or ""
                    if assignee == "unassigned":
                        if t_assignee:
                            continue
                    elif t_assignee.lower() != assignee.lower():
                        continue
                if search:
                    s_lower = search.lower()
                    title_match = s_lower in (t.get("title") or "").lower()
                    desc_match = s_lower in (t.get("description") or "").lower()
                    key_match = s_lower in (t.get("key") or "").lower()
                    if not (title_match or desc_match or key_match):
                        continue
                result.append(t)

            # Sort by order ascending, then by id descending
            result.sort(key=lambda x: (x.get("order", 0.0), -x["id"]))
            self._ensure_links(data)
            self._enrich_tasks(data, result)
            return result

    def get_task_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for t in data.get("tasks", []):
                if t["id"] == task_id:
                    self._ensure_links(data)
                    self._enrich_tasks(data, [t])
                    return t
            return None

    @staticmethod
    def _validate_hierarchy(
        tasks: List[Dict[str, Any]],
        task_id: Optional[int],
        task_type: str,
        epic_id: Optional[int],
        sirius_id: Optional[int],
    ) -> tuple[Optional[int], Optional[int]]:
        by_id = {t["id"]: t for t in tasks}
        clean_epic = int(epic_id) if epic_id else None
        clean_sirius = int(sirius_id) if sirius_id else None

        if task_type == "Сириус":
            return None, None
        if task_type == "Эпик":
            clean_epic = None

        if clean_epic is not None:
            if task_id is not None and clean_epic == task_id:
                raise ValueError("Задача не может входить сама в себя")
            ep = by_id.get(clean_epic)
            if not ep or (ep.get("task_type") or "Задача") != "Эпик":
                raise ValueError("Указанный эпик не найден или не имеет тип 'Эпик'")

        if clean_sirius is not None:
            if task_id is not None and clean_sirius == task_id:
                raise ValueError("Задача не может входить сама в себя")
            sr = by_id.get(clean_sirius)
            if not sr or (sr.get("task_type") or "Задача") != "Сириус":
                raise ValueError("Указанный Сириус не найден или не имеет тип 'Сириус'")

        return clean_epic, clean_sirius

    def create_task(
        self,
        title: str,
        description: str = "",
        story_points: Optional[float] = None,
        assignee: Optional[str] = None,
        status: str = "Бэклог",
        created_by: str = "",
        parent_task_id: Optional[int] = None,
        in_sprint: bool = False,
        order: Optional[float] = None,
        task_type: str = "Задача",
        cluster: str = "",
        epic_id: Optional[int] = None,
        sirius_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            eff_type = task_type if task_type in VALID_TASK_TYPES else "Задача"
            clean_epic, clean_sirius = self._validate_hierarchy(
                data.get("tasks", []), None, eff_type, epic_id, sirius_id
            )

            data["counters"]["task_id"] += 1
            task_id = data["counters"]["task_id"]
            task_key = f"KLUK-{task_id}"

            now = datetime.utcnow().isoformat() + "Z"
            eff_status = status if status in VALID_STATUSES else "Бэклог"
            started_at = now if eff_status == "В работе" else None
            completed_at = now if eff_status == "Завершено" else None
            eff_cluster = cluster if cluster in VALID_CLUSTERS else ""
            task_order = float(order) if order is not None else float(task_id)
            new_task = {
                "id": task_id,
                "key": task_key,
                "title": title.strip(),
                "description": description.strip(),
                "story_points": story_points,
                "status": eff_status,
                "task_type": eff_type,
                "cluster": eff_cluster,
                "epic_id": clean_epic,
                "sirius_id": clean_sirius,
                "assignee": assignee.strip() if assignee else None,
                "in_sprint": bool(in_sprint),
                "order": task_order,
                "created_by": created_by,
                "created_at": now,
                "started_at": started_at,
                "completed_at": completed_at,
                "updated_at": now,
                "parent_task_id": parent_task_id
            }
            data["tasks"].append(new_task)
            self._ensure_links(data)
            if parent_task_id and any(t["id"] == parent_task_id for t in data["tasks"]):
                data["counters"]["link_id"] = data["counters"].get("link_id", 0) + 1
                data["links"].append({
                    "id": data["counters"]["link_id"],
                    "type": "parent",
                    "source_id": parent_task_id,
                    "target_id": task_id,
                    "created_by": created_by,
                    "created_at": now
                })
            self._atomic_write(data)
            self._enrich_tasks(data, [new_task])
            return new_task

    def update_task(self, task_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            task = None
            for t in data.get("tasks", []):
                if t["id"] == task_id:
                    task = t
                    break
            if not task:
                return None

            next_type = updates.get("task_type") if updates.get("task_type") in VALID_TASK_TYPES else (task.get("task_type") or "Задача")
            next_epic = updates["epic_id"] if "epic_id" in updates else task.get("epic_id")
            next_sirius = updates["sirius_id"] if "sirius_id" in updates else task.get("sirius_id")
            if "task_type" in updates or "epic_id" in updates or "sirius_id" in updates:
                clean_epic, clean_sirius = self._validate_hierarchy(
                    data.get("tasks", []), task_id, next_type, next_epic, next_sirius
                )
                task["epic_id"] = clean_epic
                task["sirius_id"] = clean_sirius

            now = datetime.utcnow().isoformat() + "Z"
            allowed_fields = [
                "title", "description", "story_points", "status",
                "assignee", "started_at", "in_sprint", "order",
                "task_type", "cluster"
            ]
            for field in allowed_fields:
                if field in updates:
                    val = updates[field]
                    if field == "status":
                        if val not in VALID_STATUSES:
                            continue
                        if val == "В работе" and not task.get("started_at"):
                            task["started_at"] = now
                        if val == "Завершено":
                            task["completed_at"] = now
                        elif task.get("status") == "Завершено" and val != "Завершено":
                            task["completed_at"] = None
                    if field == "task_type":
                        if val not in VALID_TASK_TYPES:
                            continue
                    if field == "cluster":
                        if val is None:
                            val = ""
                        if val not in VALID_CLUSTERS:
                            continue
                    if field == "assignee" and val:
                        val = val.strip()
                    elif field == "assignee" and not val:
                        val = None
                    if field == "in_sprint":
                        val = bool(val)
                    if field == "order" and val is not None:
                        val = float(val)
                    task[field] = val

            task["updated_at"] = now
            self._atomic_write(data)
            self._ensure_links(data)
            self._enrich_tasks(data, [task])
            return task

    def reorder_tasks(self, task_ids: List[int]) -> bool:
        with _lock:
            data = self._read_data()
            id_to_order = {tid: float(idx) for idx, tid in enumerate(task_ids)}
            for t in data.get("tasks", []):
                if t["id"] in id_to_order:
                    t["order"] = id_to_order[t["id"]]
            self._atomic_write(data)
            return True

    # ------------------ COMMENTS ------------------
    def get_comments(self, task_id: int) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            comments = [c for c in data.get("comments", []) if c["task_id"] == task_id]
            comments.sort(key=lambda x: x["id"])
            return comments

    def add_comment(self, task_id: int, author: str, text: str, mentions: List[str]) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            # Verify task exists
            if not any(t["id"] == task_id for t in data.get("tasks", [])):
                raise ValueError("Задача не найдена")

            data["counters"]["comment_id"] += 1
            comment_id = data["counters"]["comment_id"]
            now = datetime.utcnow().isoformat() + "Z"

            new_comment = {
                "id": comment_id,
                "task_id": task_id,
                "author": author,
                "text": text.strip(),
                "mentions": mentions,
                "created_at": now
            }
            data["comments"].append(new_comment)
            self._atomic_write(data)
            return new_comment

    def get_comment_by_id(self, comment_id: int) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for c in data.get("comments", []):
                if c["id"] == comment_id:
                    return c
            return None

    def update_comment(self, comment_id: int, text: str, mentions: List[str]) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for c in data.get("comments", []):
                if c["id"] == comment_id:
                    c["text"] = text.strip()
                    c["mentions"] = mentions
                    c["updated_at"] = datetime.utcnow().isoformat() + "Z"
                    self._atomic_write(data)
                    return c
            return None

    def delete_comment(self, comment_id: int) -> bool:
        with _lock:
            data = self._read_data()
            comments = data.get("comments", [])
            initial_len = len(comments)
            data["comments"] = [c for c in comments if c["id"] != comment_id]
            if len(data["comments"]) < initial_len:
                self._atomic_write(data)
                return True
            return False

    # ------------------ SPRINTS ------------------
    def get_sprints(self) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            return data.get("sprints", [])

    def get_active_sprint(self) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for s in data.get("sprints", []):
                if s.get("status") == "active":
                    return s
            return None

    def create_sprint(self, name: str, goal: str = "", created_by: str = "") -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            if "sprints" not in data:
                data["sprints"] = []
            if "counters" not in data:
                data["counters"] = {}
            if "sprint_id" not in data["counters"]:
                data["counters"]["sprint_id"] = len(data["sprints"])

            now = datetime.utcnow().isoformat() + "Z"
            # Close any currently active sprint before starting a new one
            for s in data["sprints"]:
                if s.get("status") == "active":
                    s["status"] = "closed"
                    s["closed_at"] = now
                    # Completed tasks stay completed with this sprint and are not in sprint anymore
                    for t in data.get("tasks", []):
                        if (bool(t.get("in_sprint", False)) or t.get("sprint_id") == s["id"]) and t.get("status") == "Завершено":
                            t["in_sprint"] = False
                            t["sprint_id"] = s["id"]

            data["counters"]["sprint_id"] += 1
            sprint_id = data["counters"]["sprint_id"]

            new_sprint = {
                "id": sprint_id,
                "name": name.strip() if name else f"Спринт {sprint_id}",
                "goal": goal.strip() if goal else "",
                "status": "active",
                "created_at": now,
                "closed_at": None,
                "created_by": created_by
            }
            data["sprints"].append(new_sprint)

            # Link any unfinished tasks currently marked in_sprint to this new active sprint
            for t in data.get("tasks", []):
                if bool(t.get("in_sprint", False)):
                    t["sprint_id"] = sprint_id

            self._atomic_write(data)
            return new_sprint

    def close_sprint(
        self,
        sprint_id: int,
        create_next_sprint: bool = True,
        next_sprint_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            target_sprint = None
            for s in data.get("sprints", []):
                if s["id"] == sprint_id:
                    target_sprint = s
                    break

            if not target_sprint:
                return None

            now = datetime.utcnow().isoformat() + "Z"
            target_sprint["status"] = "closed"
            target_sprint["closed_at"] = now

            if "counters" not in data:
                data["counters"] = {}
            if "sprint_id" not in data["counters"]:
                data["counters"]["sprint_id"] = len(data.get("sprints", []))

            new_sprint = None
            if create_next_sprint:
                data["counters"]["sprint_id"] += 1
                new_sprint_id = data["counters"]["sprint_id"]

                if next_sprint_name and next_sprint_name.strip():
                    name = next_sprint_name.strip()
                else:
                    curr_name = target_sprint.get("name", "")
                    match = re.search(r'(\d+)\s*$', curr_name.strip())
                    if match:
                        prefix = curr_name[:match.start(1)]
                        num = int(match.group(1)) + 1
                        name = f"{prefix}{num}"
                    else:
                        name = f"Спринт {new_sprint_id}"

                new_sprint = {
                    "id": new_sprint_id,
                    "name": name,
                    "goal": "",
                    "status": "active",
                    "created_at": now,
                    "closed_at": None,
                    "created_by": target_sprint.get("created_by", "")
                }
                data["sprints"].append(new_sprint)

            # Process sprint tasks:
            # 1. Completed tasks stay associated with the closed sprint and NEVER return to backlog.
            # 2. Uncompleted tasks placed in sprint move to the new sprint, NEVER return to backlog.
            completed_count = 0
            moved_count = 0

            for t in data.get("tasks", []):
                if bool(t.get("in_sprint", False)) or t.get("sprint_id") == sprint_id:
                    if t.get("status") == "Завершено":
                        completed_count += 1
                        t["in_sprint"] = False
                        t["sprint_id"] = sprint_id
                    else:
                        # Move unfinished task to the new sprint!
                        moved_count += 1
                        t["in_sprint"] = True
                        t["sprint_id"] = new_sprint["id"] if new_sprint else None
                        t["updated_at"] = now

            self._atomic_write(data)
            return {
                "ok": True,
                "sprint": target_sprint,
                "new_sprint": new_sprint,
                "completed_count": completed_count,
                "moved_count": moved_count,
                "backlog_count": 0
            }

    # ------------------ LINKS ------------------
    @staticmethod
    def _ensure_links(data: Dict[str, Any]) -> bool:
        """Create links collection and migrate legacy parent_task_id. Returns True if changed."""
        if "links" in data:
            return False
        data["links"] = []
        data.setdefault("counters", {})["link_id"] = 0
        task_ids = {t["id"] for t in data.get("tasks", [])}
        for t in sorted(data.get("tasks", []), key=lambda x: x["id"]):
            pid = t.get("parent_task_id")
            if pid and pid in task_ids and pid != t["id"]:
                data["counters"]["link_id"] += 1
                data["links"].append({
                    "id": data["counters"]["link_id"],
                    "type": "parent",
                    "source_id": pid,
                    "target_id": t["id"],
                    "created_by": t.get("created_by", ""),
                    "created_at": t.get("created_at")
                })
        return True

    @staticmethod
    def _enrich_tasks(data: Dict[str, Any], tasks: List[Dict[str, Any]]) -> None:
        all_tasks = data.get("tasks", [])
        by_id = {t["id"]: t for t in all_tasks}
        links = data.get("links", [])

        # Precompute children per Epic and Epics per Sirius
        tasks_by_epic: Dict[int, List[Dict[str, Any]]] = {}
        epics_by_sirius: Dict[int, List[Dict[str, Any]]] = {}
        direct_by_sirius: Dict[int, List[Dict[str, Any]]] = {}
        for item in all_tasks:
            ep_id = item.get("epic_id")
            if ep_id:
                tasks_by_epic.setdefault(ep_id, []).append(item)
            sr_id = item.get("sirius_id")
            if sr_id:
                if (item.get("task_type") or "Задача") == "Эпик":
                    epics_by_sirius.setdefault(sr_id, []).append(item)
                else:
                    direct_by_sirius.setdefault(sr_id, []).append(item)

        for t in tasks:
            tid = t["id"]
            count = 0
            blocked = False
            for l in links:
                if l["source_id"] == tid or l["target_id"] == tid:
                    count += 1
                if l["type"] == "blocks" and l["target_id"] == tid:
                    blocker = by_id.get(l["source_id"])
                    if blocker and blocker.get("status") not in FINAL_STATUSES:
                        blocked = True
            t["links_count"] = count
            t["is_blocked"] = blocked
            if not t.get("task_type"):
                t["task_type"] = "Задача"
            if "cluster" not in t or t.get("cluster") is None:
                t["cluster"] = ""

            ep_id = t.get("epic_id")
            epic_obj = by_id.get(ep_id) if ep_id else None
            t["epic_id"] = ep_id if epic_obj else None
            t["epic_key"] = epic_obj["key"] if epic_obj else None
            t["epic_title"] = epic_obj["title"] if epic_obj else None

            sr_id = t.get("sirius_id") or (epic_obj.get("sirius_id") if epic_obj else None)
            sirius_obj = by_id.get(sr_id) if sr_id else None
            t["sirius_key"] = sirius_obj["key"] if sirius_obj else None
            t["sirius_title"] = sirius_obj["title"] if sirius_obj else None

            if t["task_type"] == "Эпик":
                children = tasks_by_epic.get(tid, [])
                t["children_total"] = len(children)
                t["children_done"] = sum(1 for x in children if x.get("status") == "Завершено")
                t["epics_total"] = 0
            elif t["task_type"] == "Сириус":
                epics = epics_by_sirius.get(tid, [])
                seen_ids = set()
                desc_tasks: List[Dict[str, Any]] = []
                for e in epics:
                    for ch in tasks_by_epic.get(e["id"], []):
                        if ch["id"] not in seen_ids:
                            seen_ids.add(ch["id"])
                            desc_tasks.append(ch)
                for d in direct_by_sirius.get(tid, []):
                    if d["id"] not in seen_ids:
                        seen_ids.add(d["id"])
                        desc_tasks.append(d)
                t["epics_total"] = len(epics)
                t["children_total"] = len(desc_tasks)
                t["children_done"] = sum(1 for x in desc_tasks if x.get("status") == "Завершено")
            else:
                t["epics_total"] = 0
                t["children_total"] = 0
                t["children_done"] = 0

    def get_task_hierarchy_children(self, task_id: int) -> Dict[str, List[Dict[str, Any]]]:
        with _lock:
            data = self._read_data()
            self._ensure_links(data)
            all_tasks = data.get("tasks", [])
            target = next((t for t in all_tasks if t["id"] == task_id), None)
            if not target:
                return {"epic_tasks": [], "sirius_epics": [], "sirius_tasks": []}
            tt = target.get("task_type") or "Задача"
            if tt == "Эпик":
                children = [t for t in all_tasks if t.get("epic_id") == task_id]
                self._enrich_tasks(data, children)
                return {"epic_tasks": children, "sirius_epics": [], "sirius_tasks": []}
            if tt == "Сириус":
                epics = [t for t in all_tasks if t.get("sirius_id") == task_id and (t.get("task_type") or "Задача") == "Эпик"]
                epic_ids = {e["id"] for e in epics}
                tasks_inside = [t for t in all_tasks if (t.get("task_type") or "Задача") != "Эпик" and (t.get("epic_id") in epic_ids or t.get("sirius_id") == task_id)]
                self._enrich_tasks(data, epics + tasks_inside)
                return {"epic_tasks": [], "sirius_epics": epics, "sirius_tasks": tasks_inside}
            return {"epic_tasks": [], "sirius_epics": [], "sirius_tasks": []}

    @staticmethod
    def _reachable(links: List[Dict[str, Any]], link_type: str, start: int, goal: int) -> bool:
        stack, seen = [start], set()
        while stack:
            cur = stack.pop()
            if cur == goal:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(l["target_id"] for l in links if l["type"] == link_type and l["source_id"] == cur)
        return False

    def get_links(self, task_id: int) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            self._ensure_links(data)
            by_id = {t["id"]: t for t in data.get("tasks", [])}
            result = []
            for l in data["links"]:
                if task_id not in (l["source_id"], l["target_id"]):
                    continue
                outgoing = l["source_id"] == task_id
                other = by_id.get(l["target_id"] if outgoing else l["source_id"])
                if not other:
                    continue
                result.append({
                    **l,
                    "direction": "outward" if outgoing else "inward",
                    "label": LINK_LABELS[l["type"]][0 if outgoing else 1],
                    "other_task": {
                        "id": other["id"], "key": other["key"], "title": other["title"],
                        "status": other.get("status"), "assignee": other.get("assignee")
                    }
                })
            return result

    def create_link(self, link_type: str, source_id: int, target_id: int, created_by: str) -> Dict[str, Any]:
        if link_type not in LINK_LABELS:
            raise ValueError("Неизвестный тип связи")
        if source_id == target_id:
            raise ValueError("Нельзя связать задачу саму с собой")
        with _lock:
            data = self._read_data()
            self._ensure_links(data)
            ids = {t["id"] for t in data.get("tasks", [])}
            if source_id not in ids or target_id not in ids:
                raise LookupError("Задача не найдена")
            links = data["links"]
            pair = {source_id, target_id}
            for l in links:
                same_pair = {l["source_id"], l["target_id"]} == pair
                if same_pair and l["type"] == link_type and (
                    link_type == "relates" or l["source_id"] == source_id
                ):
                    raise ValueError("Такая связь уже существует")
                if same_pair and l["type"] == link_type:
                    raise ValueError("Обратная связь уже существует (цикл)")
            if link_type == "parent":
                if any(l["type"] == "parent" and l["target_id"] == target_id for l in links):
                    raise ValueError("У задачи уже есть родитель")
            if link_type in ("parent", "blocks") and self._reachable(links, link_type, target_id, source_id):
                raise ValueError("Связь создаст цикл")
            data["counters"]["link_id"] = data["counters"].get("link_id", 0) + 1
            link = {
                "id": data["counters"]["link_id"],
                "type": link_type,
                "source_id": source_id,
                "target_id": target_id,
                "created_by": created_by,
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
            links.append(link)
            if link_type == "parent":
                for t in data["tasks"]:
                    if t["id"] == target_id:
                        t["parent_task_id"] = source_id
            self._atomic_write(data)
            return link

    def delete_link(self, link_id: int) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            self._ensure_links(data)
            for i, l in enumerate(data["links"]):
                if l["id"] == link_id:
                    data["links"].pop(i)
                    if l["type"] == "parent":
                        for t in data["tasks"]:
                            if t["id"] == l["target_id"] and t.get("parent_task_id") == l["source_id"]:
                                t["parent_task_id"] = None
                    self._atomic_write(data)
                    return l
            return None

    # ------------------ ATTACHMENTS ------------------
    def get_attachments(self, task_id: int) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            return [a for a in data.get("attachments", []) if a["task_id"] == task_id]

    def get_attachment(self, att_id: int) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            return next((a for a in data.get("attachments", []) if a["id"] == att_id), None)

    def add_attachment(self, task_id: int, filename: str, stored_name: str, size: int,
                       content_type: str, uploaded_by: str) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            counters = data.setdefault("counters", {})
            counters["attachment_id"] = counters.get("attachment_id", 0) + 1
            att = {
                "id": counters["attachment_id"],
                "task_id": task_id,
                "filename": filename,
                "stored_name": stored_name,
                "size": size,
                "content_type": content_type,
                "uploaded_by": uploaded_by,
                "created_at": datetime.now().isoformat(),
            }
            data.setdefault("attachments", []).append(att)
            self._atomic_write(data)
            return att

    def delete_attachment(self, att_id: int) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            atts = data.get("attachments", [])
            for i, a in enumerate(atts):
                if a["id"] == att_id:
                    atts.pop(i)
                    self._atomic_write(data)
                    return a
            return None

    def get_all_attachments(self) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            tasks_by_id = {t["id"]: t for t in data.get("tasks", [])}
            res = []
            for a in data.get("attachments", []):
                t = tasks_by_id.get(a.get("task_id"))
                res.append({
                    **a,
                    "task_key": t["key"] if t else None,
                    "task_title": t["title"] if t else None,
                })
            res.sort(key=lambda x: x.get("id", 0), reverse=True)
            return res

    # ------------------ NOTIFICATIONS ------------------
    def add_notification(
        self,
        username: str,
        ntype: str,
        title: str,
        message: str,
        task_id: Optional[int] = None,
        task_key: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not username:
            return None
        with _lock:
            data = self._read_data()
            counters = data.setdefault("counters", {})
            counters["notification_id"] = counters.get("notification_id", 0) + 1
            notif = {
                "id": counters["notification_id"],
                "username": username,
                "type": ntype,
                "title": title,
                "message": message,
                "task_id": task_id,
                "task_key": task_key,
                "actor": actor,
                "read": False,
                "created_at": datetime.utcnow().isoformat() + "Z",
            }
            notifs = data.setdefault("notifications", [])
            notifs.append(notif)
            if len(notifs) > 2000:
                data["notifications"] = notifs[-2000:]
            self._atomic_write(data)
            return notif

    def get_notifications(self, username: str, limit: int = 50) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            uname = username.lower()
            items = [n for n in data.get("notifications", []) if (n.get("username") or "").lower() == uname]
            unread_count = sum(1 for n in items if not n.get("read"))
            items.sort(key=lambda x: x["id"], reverse=True)
            return {"items": items[:limit], "unread_count": unread_count}

    def mark_notification_read(self, username: str, notif_id: int) -> bool:
        with _lock:
            data = self._read_data()
            uname = username.lower()
            for n in data.get("notifications", []):
                if n["id"] == notif_id and (n.get("username") or "").lower() == uname:
                    n["read"] = True
                    self._atomic_write(data)
                    return True
            return False

    def mark_all_notifications_read(self, username: str) -> int:
        with _lock:
            data = self._read_data()
            uname = username.lower()
            changed = 0
            for n in data.get("notifications", []):
                if (n.get("username") or "").lower() == uname and not n.get("read"):
                    n["read"] = True
                    changed += 1
            if changed:
                self._atomic_write(data)
            return changed

    # ------------------ ACTIVITY LOG ------------------
    def add_activity(
        self,
        username: str,
        action: str,
        task_id: Optional[int] = None,
        task_key: Optional[str] = None,
        task_title: Optional[str] = None,
        details: str = "",
    ) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            counters = data.setdefault("counters", {})
            counters["activity_id"] = counters.get("activity_id", 0) + 1
            act = {
                "id": counters["activity_id"],
                "username": username,
                "action": action,
                "task_id": task_id,
                "task_key": task_key,
                "task_title": task_title,
                "details": details,
                "created_at": datetime.utcnow().isoformat() + "Z",
            }
            acts = data.setdefault("activities", [])
            acts.append(act)
            if len(acts) > 10000:
                data["activities"] = acts[-10000:]
            self._atomic_write(data)
            return act

    def get_all_activities(
        self,
        username: Optional[str] = None,
        action: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 250,
    ) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            all_acts = list(data.get("activities", []))
            all_acts.sort(key=lambda x: (x.get("created_at") or "", x.get("id", 0)), reverse=True)

            actions = sorted({a.get("action") for a in all_acts if a.get("action")})
            today_prefix = datetime.utcnow().date().isoformat()
            today_count = sum(1 for a in all_acts if (a.get("created_at") or "").startswith(today_prefix))

            filtered = all_acts
            if username:
                ulow = username.strip().lower()
                filtered = [a for a in filtered if (a.get("username") or "").lower() == ulow]
            if action:
                filtered = [a for a in filtered if a.get("action") == action]
            if search:
                q = search.strip().lower()
                filtered = [
                    a for a in filtered
                    if q in (a.get("username") or "").lower()
                    or q in (a.get("action") or "").lower()
                    or q in (a.get("task_key") or "").lower()
                    or q in (a.get("task_title") or "").lower()
                    or q in (a.get("details") or "").lower()
                ]

            return {
                "items": filtered[:max(1, min(limit, 1000))],
                "total": len(all_acts),
                "filtered_total": len(filtered),
                "today_count": today_count,
                "actions": actions,
            }

    def get_user_activities(self, username: str, limit: int = 100) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            uname = username.lower()
            acts = [a for a in data.get("activities", []) if (a.get("username") or "").lower() == uname]
            acts.sort(key=lambda x: x.get("created_at") or "", reverse=True)

            # Task stats for this user
            tasks = data.get("tasks", [])
            assigned = [t for t in tasks if (t.get("assignee") or "").lower() == uname]
            created = [t for t in tasks if (t.get("created_by") or "").lower() == uname]
            completed = [t for t in assigned if t.get("status") == "Завершено"]
            in_progress = [t for t in assigned if t.get("status") == "В работе"]
            done_sp = sum(float(t.get("story_points") or 0) for t in completed)

            # If no explicit activity entries yet for older tasks, synthesize timeline from tasks/comments
            if not acts:
                synth = []
                for t in tasks:
                    if (t.get("created_by") or "").lower() == uname:
                        synth.append({
                            "id": 0,
                            "username": username,
                            "action": "task_created",
                            "task_id": t["id"],
                            "task_key": t["key"],
                            "task_title": t["title"],
                            "details": f"Создана задача ({t.get('task_type') or 'Задача'})",
                            "created_at": t.get("created_at"),
                        })
                    if (t.get("assignee") or "").lower() == uname and t.get("status") == "Завершено":
                        synth.append({
                            "id": 0,
                            "username": username,
                            "action": "task_status",
                            "task_id": t["id"],
                            "task_key": t["key"],
                            "task_title": t["title"],
                            "details": "Статус: Завершено",
                            "created_at": t.get("completed_at") or t.get("updated_at"),
                        })
                for c in data.get("comments", []):
                    if (c.get("author") or "").lower() == uname:
                        task_obj = next((t for t in tasks if t["id"] == c["task_id"]), None)
                        if task_obj:
                            synth.append({
                                "id": 0,
                                "username": username,
                                "action": "comment_added",
                                "task_id": task_obj["id"],
                                "task_key": task_obj["key"],
                                "task_title": task_obj["title"],
                                "details": c["text"][:140],
                                "created_at": c.get("created_at"),
                            })
                synth.sort(key=lambda x: x.get("created_at") or "", reverse=True)
                acts = synth

            return {
                "items": acts[:limit],
                "stats": {
                    "assigned_total": len(assigned),
                    "created_total": len(created),
                    "completed_total": len(completed),
                    "in_progress_total": len(in_progress),
                    "completed_sp": done_sp,
                },
            }

    # ------------------ ANALYTICS / CHARTS ------------------
    def get_analytics(self) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            tasks = data.get("tasks", [])
            sprints = data.get("sprints", [])
            users = data.get("users", [])

            by_status = {s: 0 for s in VALID_STATUSES}
            by_type = {tt: 0 for tt in VALID_TASK_TYPES}
            by_cluster = {"Без кластера": 0, "Эпик": 0, "Сириус": 0}
            total_sp = 0.0
            done_sp = 0.0

            user_map = {u["username"].lower(): u.get("display_name", u["username"]) for u in users}
            by_assignee: Dict[str, Dict[str, Any]] = {}

            for t in tasks:
                st = t.get("status") or "Бэклог"
                by_status[st] = by_status.get(st, 0) + 1

                tt = t.get("task_type") or "Задача"
                by_type[tt] = by_type.get(tt, 0) + 1

                cl = t.get("cluster") or ""
                cl_label = cl if cl else "Без кластера"
                by_cluster[cl_label] = by_cluster.get(cl_label, 0) + 1

                sp = float(t.get("story_points") or 0)
                total_sp += sp
                if st == "Завершено":
                    done_sp += sp

                assignee_raw = t.get("assignee") or ""
                a_key = assignee_raw.lower() if assignee_raw else "__unassigned__"
                if a_key not in by_assignee:
                    by_assignee[a_key] = {
                        "username": assignee_raw or "unassigned",
                        "display_name": user_map.get(a_key, assignee_raw) if assignee_raw else "Не назначен",
                        "total": 0,
                        "done": 0,
                        "in_progress": 0,
                        "sp": 0.0,
                        "done_sp": 0.0,
                    }
                entry = by_assignee[a_key]
                entry["total"] += 1
                entry["sp"] += sp
                if st == "Завершено":
                    entry["done"] += 1
                    entry["done_sp"] += sp
                elif st == "В работе":
                    entry["in_progress"] += 1

            # Sprint velocity
            sprint_stats = []
            for s in sprints:
                sid = s["id"]
                s_tasks = [t for t in tasks if t.get("sprint_id") == sid or (s.get("status") == "active" and t.get("in_sprint"))]
                s_done = [t for t in s_tasks if t.get("status") == "Завершено"]
                sprint_stats.append({
                    "id": sid,
                    "name": s["name"],
                    "status": s.get("status"),
                    "total_tasks": len(s_tasks),
                    "done_tasks": len(s_done),
                    "total_sp": sum(float(t.get("story_points") or 0) for t in s_tasks),
                    "done_sp": sum(float(t.get("story_points") or 0) for t in s_done),
                })

            # Last 14 days created vs completed
            today = datetime.utcnow().date()
            days = [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
            created_day = {d: 0 for d in days}
            completed_day = {d: 0 for d in days}
            for t in tasks:
                cd = (t.get("created_at") or "")[:10]
                if cd in created_day:
                    created_day[cd] += 1
                if t.get("status") == "Завершено":
                    fd = (t.get("completed_at") or t.get("updated_at") or "")[:10]
                    if fd in completed_day:
                        completed_day[fd] += 1

            timeline = [
                {"date": d, "label": d[5:], "created": created_day[d], "completed": completed_day[d]}
                for d in days
            ]

            by_id = {t["id"]: t for t in tasks}
            epics_stats = []
            for t in tasks:
                if (t.get("task_type") or "Задача") == "Эпик":
                    ch = [x for x in tasks if x.get("epic_id") == t["id"]]
                    done_ch = [x for x in ch if x.get("status") == "Завершено"]
                    sr = by_id.get(t.get("sirius_id")) if t.get("sirius_id") else None
                    epics_stats.append({
                        "id": t["id"],
                        "key": t["key"],
                        "title": t["title"],
                        "status": t.get("status"),
                        "sirius_key": sr["key"] if sr else None,
                        "sirius_title": sr["title"] if sr else None,
                        "total_tasks": len(ch),
                        "done_tasks": len(done_ch),
                        "total_sp": sum(float(x.get("story_points") or 0) for x in ch),
                        "done_sp": sum(float(x.get("story_points") or 0) for x in done_ch),
                    })

            sirius_stats = []
            for t in tasks:
                if (t.get("task_type") or "Задача") == "Сириус":
                    ep_list = [x for x in tasks if x.get("sirius_id") == t["id"] and (x.get("task_type") or "Задача") == "Эпик"]
                    ep_ids = {e["id"] for e in ep_list}
                    ch = [x for x in tasks if (x.get("task_type") or "Задача") != "Эпик" and (x.get("epic_id") in ep_ids or x.get("sirius_id") == t["id"])]
                    done_ch = [x for x in ch if x.get("status") == "Завершено"]
                    sirius_stats.append({
                        "id": t["id"],
                        "key": t["key"],
                        "title": t["title"],
                        "status": t.get("status"),
                        "epics_count": len(ep_list),
                        "total_tasks": len(ch),
                        "done_tasks": len(done_ch),
                        "total_sp": sum(float(x.get("story_points") or 0) for x in ch),
                        "done_sp": sum(float(x.get("story_points") or 0) for x in done_ch),
                    })

            return {
                "summary": {
                    "total_tasks": len(tasks),
                    "done_tasks": by_status.get("Завершено", 0),
                    "in_progress_tasks": by_status.get("В работе", 0),
                    "backlog_tasks": by_status.get("Бэклог", 0),
                    "total_sp": total_sp,
                    "done_sp": done_sp,
                    "users_count": len(users),
                    "epics_count": len(epics_stats),
                    "sirius_count": len(sirius_stats),
                },
                "by_status": [{"label": k, "count": v} for k, v in by_status.items()],
                "by_type": [{"label": k, "count": v} for k, v in by_type.items()],
                "by_cluster": [{"label": k, "count": v} for k, v in by_cluster.items()],
                "epics": epics_stats,
                "siriuses": sirius_stats,
                "by_assignee": sorted(by_assignee.values(), key=lambda x: (-x["total"], x["display_name"])),
                "sprints": sprint_stats,
                "timeline": timeline,
            }


ATTACHMENTS_DIR = os.path.join(os.path.dirname(DB_FILE_PATH), "klukva_attachments")
AVATARS_DIR = os.path.join(ATTACHMENTS_DIR, "avatars")

db = JSONDatabase()
