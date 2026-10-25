"""
FastAPI route handlers for Klukva task tracker.
"""

import os
import sys
import subprocess
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.auth import (
    create_session,
    get_current_user,
    hash_password,
    invalidate_session,
    verify_password,
)
from backend.db import VALID_STATUSES, db

router = APIRouter(prefix="/api")


# --- Pydantic Schemas ---
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=3, max_length=128)
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = ""
    story_points: Optional[float] = None
    assignee: Optional[str] = None
    status: Optional[str] = "Бэклог"
    in_sprint: Optional[bool] = False


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    story_points: Optional[float] = None
    status: Optional[str] = None
    assignee: Optional[str] = None
    in_sprint: Optional[bool] = None
    sprint_id: Optional[int] = None
    order: Optional[float] = None


class ReorderRequest(BaseModel):
    task_ids: List[int]


class SprintCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    goal: Optional[str] = ""


class SprintCloseRequest(BaseModel):
    create_next_sprint: bool = True
    next_sprint_name: Optional[str] = None


class SplitPartialRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = ""
    story_points: Optional[float] = None
    assignee: Optional[str] = None


class CommentCreateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


# --- Helper: Extract Mentions ---
def extract_mentions(text: str) -> List[str]:
    """Finds all @username patterns in text and verifies against existing usernames."""
    raw_mentions = set(re.findall(r"@([a-zA-Z0-9_\-\.]+)", text))
    if not raw_mentions:
        return []
    existing_users = {u["username"].lower(): u["username"] for u in db.get_users()}
    valid_mentions = []
    for rm in raw_mentions:
        if rm.lower() in existing_users:
            valid_mentions.append(existing_users[rm.lower()])
    return valid_mentions


# ============================================================================
# AUTHENTICATION
# ============================================================================
@router.post("/auth/register")
def register(req: RegisterRequest):
    username_clean = req.username.strip()
    if not re.match(r"^[a-zA-Z0-9_\-]+$", username_clean):
        raise HTTPException(
            status_code=400,
            detail="Имя пользователя может содержать только латинские буквы, цифры, дефис и подчеркивание"
        )
    existing = db.get_user_by_username(username_clean)
    if existing:
        raise HTTPException(status_code=400, detail="Пользователь с таким логином уже существует")

    pw_hash = hash_password(req.password)
    user = db.create_user(
        username=username_clean,
        password_hash=pw_hash,
        display_name=req.display_name.strip() if req.display_name else username_clean
    )
    token = create_session(user["id"], user["username"])
    return {"token": token, "user": user}


@router.post("/auth/login")
def login(req: LoginRequest):
    user_record = db.get_user_by_username(req.username.strip())
    if not user_record or not verify_password(req.password, user_record.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")

    token = create_session(user_record["id"], user_record["username"])
    user_public = {
        "id": user_record["id"],
        "username": user_record["username"],
        "display_name": user_record.get("display_name", user_record["username"]),
        "created_at": user_record.get("created_at")
    }
    return {"token": token, "user": user_public}


@router.post("/auth/logout")
def logout(current_user: Dict = Depends(get_current_user)):
    # Simply successful response; frontend removes token
    return {"ok": True}


@router.get("/auth/me")
def me(current_user: Dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "display_name": current_user.get("display_name", current_user["username"]),
        "created_at": current_user.get("created_at")
    }


@router.get("/users")
def list_users(current_user: Dict = Depends(get_current_user)):
    return db.get_users()


# ============================================================================
# TASKS
# ============================================================================
@router.get("/tasks")
def list_tasks(
    status: Optional[str] = Query(None),
    story_points: Optional[float] = Query(None),
    min_sp: Optional[float] = Query(None),
    max_sp: Optional[float] = Query(None),
    assignee: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    exclude_backlog: bool = Query(False),
    in_sprint: Optional[bool] = Query(None),
    current_user: Dict = Depends(get_current_user)
):
    tasks = db.get_tasks(
        status=status,
        story_points=story_points,
        min_sp=min_sp,
        max_sp=max_sp,
        assignee=assignee,
        search=search,
        exclude_backlog=exclude_backlog,
        in_sprint=in_sprint
    )
    return tasks


@router.post("/tasks", status_code=201)
def create_task(req: TaskCreateRequest, current_user: Dict = Depends(get_current_user)):
    status_val = req.status if req.status in VALID_STATUSES else "Бэклог"
    new_task = db.create_task(
        title=req.title,
        description=req.description or "",
        story_points=req.story_points,
        assignee=req.assignee,
        status=status_val,
        in_sprint=bool(req.in_sprint),
        created_by=current_user["username"]
    )
    return new_task


@router.post("/tasks/reorder")
def reorder_tasks(req: ReorderRequest, current_user: Dict = Depends(get_current_user)):
    db.reorder_tasks(req.task_ids)
    return {"ok": True}


@router.post("/tasks/{task_id}/toggle-sprint")
def toggle_sprint(task_id: int, current_user: Dict = Depends(get_current_user)):
    task = db.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    new_val = not bool(task.get("in_sprint", False))
    active = db.get_active_sprint()
    sprint_id = active["id"] if (new_val and active) else (None if not new_val else task.get("sprint_id"))
    updated = db.update_task(task_id, {"in_sprint": new_val, "sprint_id": sprint_id})
    return updated


# ============================================================================
# SPRINTS
# ============================================================================
@router.get("/sprints")
def list_sprints(current_user: Dict = Depends(get_current_user)):
    return db.get_sprints()


@router.get("/sprints/active")
def get_active_sprint(current_user: Dict = Depends(get_current_user)):
    return db.get_active_sprint()


@router.post("/sprints", status_code=201)
def create_sprint(req: SprintCreateRequest, current_user: Dict = Depends(get_current_user)):
    new_sprint = db.create_sprint(
        name=req.name,
        goal=req.goal or "",
        created_by=current_user["username"]
    )
    return new_sprint


@router.post("/sprints/{sprint_id}/close")
def close_sprint(
    sprint_id: int,
    req: Optional[SprintCloseRequest] = None,
    current_user: Dict = Depends(get_current_user)
):
    create_next = req.create_next_sprint if req else True
    next_name = req.next_sprint_name if req else None
    result = db.close_sprint(sprint_id, create_next_sprint=create_next, next_sprint_name=next_name)
    if not result:
        raise HTTPException(status_code=404, detail="Спринт не найден")
    return result


@router.get("/tasks/{task_id}")
def get_task(task_id: int, current_user: Dict = Depends(get_current_user)):
    task = db.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    comments = db.get_comments(task_id)
    return {**task, "comments": comments}


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int,
    req: TaskUpdateRequest,
    current_user: Dict = Depends(get_current_user)
):
    updates = req.model_dump(exclude_unset=True)
    if "in_sprint" in updates:
        active = db.get_active_sprint()
        if updates["in_sprint"] and active:
            updates["sprint_id"] = active["id"]
        elif not updates["in_sprint"]:
            updates["sprint_id"] = None

    task = db.update_task(task_id, updates)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task


@router.post("/tasks/{task_id}/take")
def take_task(task_id: int, current_user: Dict = Depends(get_current_user)):
    """
    Action from Backlog: pressing '+' assigns task to current user
    and changes status to 'В работе'.
    """
    task = db.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    updated = db.update_task(
        task_id,
        {
            "assignee": current_user["username"],
            "status": "В работе"
        }
    )
    return updated


@router.post("/tasks/{task_id}/split-partial")
def split_partial_task(
    task_id: int,
    req: SplitPartialRequest,
    current_user: Dict = Depends(get_current_user)
):
    """
    Feature: For tasks marked 'Реализовано частично', create a new task in Backlog
    for the remaining unfinished part, linked to original.
    """
    orig_task = db.get_task_by_id(task_id)
    if not orig_task:
        raise HTTPException(status_code=404, detail="Исходная задача не найдена")

    # Set parent status to 'Реализовано частично' if not already
    if orig_task.get("status") != "Реализовано частично":
        db.update_task(task_id, {"status": "Реализовано частично"})
        orig_task["status"] = "Реализовано частично"

    # Create new backlog task
    new_task = db.create_task(
        title=req.title,
        description=req.description or f"Нереализованная часть из {orig_task['key']}: {orig_task['title']}",
        story_points=req.story_points,
        assignee=req.assignee,
        status="Бэклог",
        created_by=current_user["username"],
        parent_task_id=task_id
    )

    # Automatically add comment to original task referencing the new backlog task
    db.add_comment(
        task_id=task_id,
        author="Klukva",
        text=f"Нереализованная часть вынесена в бэклог: {new_task['key']} - {new_task['title']}",
        mentions=[]
    )

    return {
        "original_task": db.get_task_by_id(task_id),
        "backlog_task": new_task
    }


# ============================================================================
# COMMENTS & MENTIONS
# ============================================================================
@router.get("/tasks/{task_id}/comments")
def list_comments(task_id: int, current_user: Dict = Depends(get_current_user)):
    task = db.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return db.get_comments(task_id)


@router.post("/tasks/{task_id}/comments", status_code=201)
def add_comment(
    task_id: int,
    req: CommentCreateRequest,
    current_user: Dict = Depends(get_current_user)
):
    task = db.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    mentions = extract_mentions(req.text)
    comment = db.add_comment(
        task_id=task_id,
        author=current_user["username"],
        text=req.text,
        mentions=mentions
    )
    return comment


@router.patch("/tasks/{task_id}/comments/{comment_id}")
def update_comment(
    task_id: int,
    comment_id: int,
    req: CommentCreateRequest,
    current_user: Dict = Depends(get_current_user)
):
    comment = db.get_comment_by_id(comment_id)
    if not comment or comment.get("task_id") != task_id:
        raise HTTPException(status_code=404, detail="Комментарий не найден")

    if comment["author"] != current_user["username"]:
        raise HTTPException(status_code=403, detail="Редактировать комментарий может только его автор")

    mentions = extract_mentions(req.text)
    updated = db.update_comment(comment_id, req.text, mentions)
    return updated


@router.delete("/tasks/{task_id}/comments/{comment_id}")
def delete_comment(
    task_id: int,
    comment_id: int,
    current_user: Dict = Depends(get_current_user)
):
    comment = db.get_comment_by_id(comment_id)
    if not comment or comment.get("task_id") != task_id:
        raise HTTPException(status_code=404, detail="Комментарий не найден")

    if comment["author"] != current_user["username"]:
        raise HTTPException(status_code=403, detail="Удалять комментарий может только его автор")

    success = db.delete_comment(comment_id)
    return {"ok": success}


# ============================================================================
# SYSTEM / UPDATE
# ============================================================================
def find_repo_dir() -> str:
    env_dir = os.environ.get("KLUKVA_REPO_DIR")
    if env_dir and os.path.exists(env_dir):
        return os.path.abspath(env_dir)

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        parent = os.path.dirname(exe_dir)
        if os.path.exists(os.path.join(parent, ".git")):
            return parent
        if os.path.exists(os.path.join(exe_dir, ".git")):
            return exe_dir

    this_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.exists(os.path.join(this_dir, ".git")):
        return this_dir

    cwd = os.getcwd()
    if os.path.exists(os.path.join(cwd, ".git")):
        return cwd

    return this_dir


def pull_repo_changes(repo_dir: str) -> Dict[str, Any]:
    try:
        check_git = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        if check_git.returncode != 0:
            return {"ok": False, "error": "Git не найден в системе."}
    except Exception:
        return {"ok": False, "error": "Git не найден в системе. Убедитесь, что Git установлен."}

    git_dir = os.path.join(repo_dir, ".git")
    if not os.path.exists(git_dir):
        return {"ok": False, "error": f"Каталог {repo_dir} не является Git-репозиторием."}

    try:
        res = subprocess.run(
            ["git", "pull", "--autostash", "origin", "main"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=45,
            encoding="utf-8",
            errors="replace"
        )
        stdout = (res.stdout or "").strip()
        stderr = (res.stderr or "").strip()

        if res.returncode != 0:
            res2 = subprocess.run(
                ["git", "pull", "--autostash"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=45,
                encoding="utf-8",
                errors="replace"
            )
            stdout = (res2.stdout or "").strip()
            stderr = (res2.stderr or "").strip()
            if res2.returncode != 0:
                return {
                    "ok": False,
                    "error": stderr or stdout or "Ошибка при выполнении git pull",
                    "output": stdout
                }

        is_updated = "Already up to date" not in stdout and "Уже обновлено" not in stdout and "Already up-to-date" not in stdout
        py_changed = any(".py" in line for line in stdout.splitlines())

        return {
            "ok": True,
            "updated": is_updated,
            "py_changed": py_changed,
            "message": stdout or "Успешно обновлено",
            "output": stdout
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }


@router.post("/system/update")
def trigger_update():
    """Pulls latest changes from Git repository."""
    repo_dir = find_repo_dir()
    return pull_repo_changes(repo_dir)

