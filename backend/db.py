"""
JSON Database module for Klukva task tracker.
Thread-safe, atomic file writes to prevent any data corruption.
"""

import json
import os
import tempfile
import threading
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

DB_FILE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "klukva_db.json"))

_lock = threading.Lock()

DEFAULT_DB: Dict[str, Any] = {
    "users": [],
    "tasks": [],
    "comments": [],
    "sprints": [],
    "counters": {
        "user_id": 0,
        "task_id": 0,
        "comment_id": 0,
        "sprint_id": 0
    }
}

VALID_STATUSES = [
    "Бэклог",
    "В работе",
    "Завершено",
    "Не реализовано",
    "Реализовано частично"
]


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

    # ------------------ USERS ------------------
    def get_users(self) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            return [
                {
                    "id": u["id"],
                    "username": u["username"],
                    "display_name": u.get("display_name", u["username"]),
                    "created_at": u.get("created_at")
                }
                for u in data.get("users", [])
            ]

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for u in data.get("users", []):
                if u["username"].lower() == username.lower():
                    return u
            return None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for u in data.get("users", []):
                if u["id"] == user_id:
                    return u
            return None

    def create_user(self, username: str, password_hash: str, display_name: str) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            for u in data.get("users", []):
                if u["username"].lower() == username.lower():
                    raise ValueError(f"Пользователь '{username}' уже существует")

            data["counters"]["user_id"] += 1
            user_id = data["counters"]["user_id"]
            new_user = {
                "id": user_id,
                "username": username,
                "password_hash": password_hash,
                "display_name": display_name or username,
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
            data["users"].append(new_user)
            self._atomic_write(data)
            return {
                "id": new_user["id"],
                "username": new_user["username"],
                "display_name": new_user["display_name"],
                "created_at": new_user["created_at"]
            }

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
        in_sprint: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            tasks = data.get("tasks", [])

            result = []
            for t in tasks:
                if status and t.get("status") != status:
                    continue
                if exclude_backlog and t.get("status") == "Бэклог":
                    continue
                if in_sprint is not None and bool(t.get("in_sprint", False)) != in_sprint:
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
            return result

    def get_task_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        with _lock:
            data = self._read_data()
            for t in data.get("tasks", []):
                if t["id"] == task_id:
                    return t
            return None

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
        order: Optional[float] = None
    ) -> Dict[str, Any]:
        with _lock:
            data = self._read_data()
            data["counters"]["task_id"] += 1
            task_id = data["counters"]["task_id"]
            task_key = f"KLUK-{task_id}"

            now = datetime.utcnow().isoformat() + "Z"
            started_at = now if status == "В работе" else None
            task_order = float(order) if order is not None else float(task_id)
            new_task = {
                "id": task_id,
                "key": task_key,
                "title": title.strip(),
                "description": description.strip(),
                "story_points": story_points,
                "status": status if status in VALID_STATUSES else "Бэклог",
                "assignee": assignee.strip() if assignee else None,
                "in_sprint": bool(in_sprint),
                "order": task_order,
                "created_by": created_by,
                "created_at": now,
                "started_at": started_at,
                "updated_at": now,
                "parent_task_id": parent_task_id
            }
            data["tasks"].append(new_task)
            self._atomic_write(data)
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

            allowed_fields = [
                "title", "description", "story_points", "status",
                "assignee", "started_at", "in_sprint", "order"
            ]
            for field in allowed_fields:
                if field in updates:
                    val = updates[field]
                    if field == "status" and val not in VALID_STATUSES:
                        continue
                    if field == "status" and val == "В работе" and not task.get("started_at"):
                        task["started_at"] = datetime.utcnow().isoformat() + "Z"
                    if field == "assignee" and val:
                        val = val.strip()
                    elif field == "assignee" and not val:
                        val = None
                    if field == "in_sprint":
                        val = bool(val)
                    if field == "order" and val is not None:
                        val = float(val)
                    task[field] = val

            task["updated_at"] = datetime.utcnow().isoformat() + "Z"
            self._atomic_write(data)
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


db = JSONDatabase()
