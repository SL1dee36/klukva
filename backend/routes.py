"""
FastAPI route handlers for Klukva task tracker.
"""

import os
import sys
import subprocess
import threading
import re
import uuid
import json
import shutil
import tempfile
import zipfile
import urllib.request
import urllib.error
import mimetypes
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.auth import (
    JWT_TOTP_CHALLENGE_TTL,
    create_jwt,
    create_session,
    decode_jwt,
    generate_pat_token,
    generate_totp_secret,
    get_current_user,
    get_totp_uri,
    get_user_from_token,
    has_min_role,
    hash_password,
    invalidate_session,
    parse_device_name,
    require_role,
    require_system_user,
    verify_password,
    verify_totp,
)
from backend.db import (
    ATTACHMENTS_DIR,
    AVATARS_DIR,
    DB_FILE_PATH,
    VALID_CLUSTERS,
    VALID_ROLES,
    VALID_STATUSES,
    VALID_TASK_TYPES,
    db,
)
from backend.qr import make_qr_svg

router = APIRouter(prefix="/api")


# --- Pydantic Schemas ---
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=3, max_length=128)
    display_name: Optional[str] = None
    trust_device: bool = False
    device_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None
    trust_device: bool = False
    device_name: Optional[str] = None


class TotpLoginRequest(BaseModel):
    challenge_token: str
    code: str
    trust_device: Optional[bool] = None
    device_name: Optional[str] = None


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=80)


class PreferencesUpdateRequest(BaseModel):
    theme: Optional[str] = None
    ui_style: Optional[str] = None
    accent: Optional[str] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=3, max_length=128)


class CredentialsChangeRequest(BaseModel):
    current_password: str
    new_username: str = Field(..., min_length=2, max_length=32)
    new_password: str = Field(..., min_length=4, max_length=128)


class TotpCodeRequest(BaseModel):
    code: str


class TotpDisableRequest(BaseModel):
    password: Optional[str] = None
    code: Optional[str] = None


class PatCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    expires_days: Optional[int] = Field(default=90, ge=1, le=3650)


class RoleUpdateRequest(BaseModel):
    role: str


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = ""
    story_points: Optional[float] = None
    assignee: Optional[str] = None
    status: Optional[str] = "Бэклог"
    in_sprint: Optional[bool] = False
    task_type: Optional[str] = "Задача"
    cluster: Optional[str] = ""
    epic_id: Optional[int] = None
    sirius_id: Optional[int] = None


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    story_points: Optional[float] = None
    status: Optional[str] = None
    assignee: Optional[str] = None
    in_sprint: Optional[bool] = None
    sprint_id: Optional[int] = None
    order: Optional[float] = None
    task_type: Optional[str] = None
    cluster: Optional[str] = None
    epic_id: Optional[int] = None
    sirius_id: Optional[int] = None


class ReorderRequest(BaseModel):
    task_ids: List[int]


class SprintCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    goal: Optional[str] = ""
    status: Optional[str] = "active"


class SprintUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    goal: Optional[str] = Field(None, max_length=500)


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


# --- Helper: Complete login & build trusted device ---
def _complete_login(user_record: Dict[str, Any], request: Request, trust_device: bool, device_name: Optional[str]) -> Dict[str, Any]:
    device_info = None
    device_id = None
    if trust_device:
        device_id = uuid.uuid4().hex[:16]
        now_dt = datetime.utcnow()
        ua = request.headers.get("user-agent", "")
        ip = request.client.host if request.client else ""
        device_info = {
            "id": device_id,
            "name": parse_device_name(ua, device_name),
            "ip": ip,
            "user_agent": ua[:250],
            "created_at": now_dt.isoformat() + "Z",
            "last_used_at": now_dt.isoformat() + "Z",
            "expires_at": (now_dt + timedelta(days=90)).isoformat() + "Z",
        }

    user_public = db.record_login(user_record["id"], device_info=device_info)
    role = user_public["role"] if user_public else user_record.get("role", "member")
    token = create_session(
        user_record["id"],
        user_record["username"],
        role=role,
        trusted=trust_device,
        device_id=device_id,
    )
    return {"token": token, "user": user_public, "trusted_device": device_info}


def _notify_task_change(task: Dict[str, Any], actor: str, ntype: str, title: str, message: str, targets: List[Optional[str]]) -> None:
    seen = set()
    for target in targets:
        if not target:
            continue
        t_low = target.lower()
        if t_low == actor.lower() or t_low in seen:
            continue
        seen.add(t_low)
        db.add_notification(
            username=target,
            ntype=ntype,
            title=title,
            message=message,
            task_id=task["id"],
            task_key=task["key"],
            actor=actor,
        )


# ============================================================================
# AUTHENTICATION
# ============================================================================
@router.post("/auth/register")
def register(req: RegisterRequest, request: Request):
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
    db.add_activity(user["username"], "auth_register", details=f"Регистрация пользователя @{user['username']} ({user['role']})")
    user_record = db.get_user_by_id(user["id"])
    return _complete_login(user_record, request, req.trust_device, req.device_name)


@router.post("/auth/login")
def login(req: LoginRequest, request: Request):
    uname_clean = req.username.strip()
    if uname_clean.lower() == "admin":
        db.ensure_system_admin()
    user_record = db.get_user_by_username(uname_clean)
    if not user_record or not verify_password(req.password, user_record.get("password_hash", "")):
        ip = request.client.host if request.client else ""
        db.add_activity(uname_clean or "unknown", "auth_login_failed", details=f"Неудачный вход (IP: {ip})")
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")

    if user_record.get("totp_enabled"):
        if req.totp_code:
            if not verify_totp(user_record.get("totp_secret"), req.totp_code):
                raise HTTPException(status_code=401, detail="Неверный код 2FA (TOTP)")
        else:
            challenge = create_jwt(
                user_id=user_record["id"],
                username=user_record["username"],
                role=user_record.get("role", "member"),
                trusted=req.trust_device,
                ttl_seconds=JWT_TOTP_CHALLENGE_TTL,
                scope="totp_verify",
            )
            return {
                "requires_totp": True,
                "challenge_token": challenge,
                "username": user_record["username"],
            }

    res = _complete_login(user_record, request, req.trust_device, req.device_name)
    db.add_activity(
        user_record["username"],
        "auth_login",
        details=f"Вход в систему ({'доверенное устройство' if req.trust_device else 'обычная сессия'})",
    )
    return res


@router.post("/auth/login/totp")
def login_totp(req: TotpLoginRequest, request: Request):
    payload = decode_jwt(req.challenge_token, expected_scope="totp_verify")
    if not payload:
        raise HTTPException(status_code=401, detail="Срок проверки 2FA истек, войдите заново")
    user_record = db.get_user_by_id(int(payload["sub"]))
    if not user_record or not user_record.get("totp_enabled"):
        raise HTTPException(status_code=401, detail="Пользователь или TOTP не найден")
    if not verify_totp(user_record.get("totp_secret"), req.code):
        raise HTTPException(status_code=401, detail="Неверный код 2FA (TOTP)")

    trust = req.trust_device if req.trust_device is not None else bool(payload.get("trusted", False))
    res = _complete_login(user_record, request, trust, req.device_name)
    db.add_activity(
        user_record["username"],
        "auth_login",
        details=f"Вход с 2FA ({'доверенное устройство' if trust else 'обычная сессия'})",
    )
    return res


@router.post("/auth/logout")
def logout(revoke_device: bool = Query(False), current_user: Dict = Depends(get_current_user)):
    raw_token = current_user.get("_raw_token")
    if raw_token:
        invalidate_session(raw_token)
    jwt_payload = current_user.get("_jwt_payload") or {}
    if revoke_device and jwt_payload.get("device_id"):
        db.remove_trusted_device(current_user["id"], jwt_payload["device_id"])
    db.add_activity(current_user["username"], "auth_logout", details="Выход из системы")
    return {"ok": True}


@router.get("/auth/me")
def me(current_user: Dict = Depends(get_current_user)):
    fresh = db.get_user_by_id(current_user["id"]) or current_user
    notifs = db.get_notifications(fresh["username"], limit=1)
    jwt_payload = current_user.get("_jwt_payload") or {}
    avatar = fresh.get("avatar")
    return {
        "id": fresh["id"],
        "username": fresh["username"],
        "display_name": fresh.get("display_name", fresh["username"]),
        "role": fresh.get("role", "member"),
        "is_system": bool(fresh.get("is_system", False)),
        "must_change_credentials": bool(fresh.get("must_change_credentials", False)),
        "avatar_url": f"/api/users/{fresh['username']}/avatar?v={avatar}" if avatar else None,
        "created_at": fresh.get("created_at"),
        "last_login_at": fresh.get("last_login_at"),
        "login_count": fresh.get("login_count", 0),
        "totp_enabled": bool(fresh.get("totp_enabled", False)),
        "unread_notifications_count": notifs["unread_count"],
        "current_device_id": jwt_payload.get("device_id"),
        "preferences": db.normalize_preferences(fresh.get("preferences")),
    }


@router.get("/users")
def list_users(current_user: Dict = Depends(get_current_user)):
    return db.get_users()


@router.patch("/users/{user_id}/role")
def update_user_role(user_id: int, req: RoleUpdateRequest, current_user: Dict = Depends(require_role("admin"))):
    if req.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Недопустимая роль")
    try:
        updated = db.update_user_role(user_id, req.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    db.add_activity(current_user["username"], "role_updated", details=f"Роль @{updated['username']} -> {req.role}")
    return updated


# ============================================================================
# USER PROFILE, AVATAR, TOTP, TRUSTED DEVICES, PATs, ACTIVITY
# ============================================================================
@router.get("/profile")
def get_own_profile(current_user: Dict = Depends(get_current_user)):
    fresh = db.get_user_by_id(current_user["id"]) or current_user
    jwt_payload = current_user.get("_jwt_payload") or {}
    cur_dev_id = jwt_payload.get("device_id")
    devices = [
        {**d, "is_current": (d.get("id") == cur_dev_id)}
        for d in db.get_trusted_devices(fresh["id"])
    ]
    avatar = fresh.get("avatar")
    return {
        "user": {
            "id": fresh["id"],
            "username": fresh["username"],
            "display_name": fresh.get("display_name", fresh["username"]),
            "role": fresh.get("role", "member"),
            "is_system": bool(fresh.get("is_system", False)),
            "must_change_credentials": bool(fresh.get("must_change_credentials", False)),
            "avatar_url": f"/api/users/{fresh['username']}/avatar?v={avatar}" if avatar else None,
            "created_at": fresh.get("created_at"),
            "last_login_at": fresh.get("last_login_at"),
            "login_count": fresh.get("login_count", 0),
            "totp_enabled": bool(fresh.get("totp_enabled", False)),
            "preferences": db.normalize_preferences(fresh.get("preferences")),
        },
        "trusted_devices": devices,
        "pat_tokens": db.get_pats(fresh["id"]),
        "activity": db.get_user_activities(fresh["username"]),
    }


@router.get("/users/{username}/profile")
def get_public_user_profile(username: str, current_user: Dict = Depends(get_current_user)):
    target = db.get_user_by_username(username)
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    avatar = target.get("avatar")
    # Never expose trusted_devices, totp_secret, or pat_tokens for another user
    return {
        "user": {
            "id": target["id"],
            "username": target["username"],
            "display_name": target.get("display_name", target["username"]),
            "role": target.get("role", "member"),
            "avatar_url": f"/api/users/{target['username']}/avatar?v={avatar}" if avatar else None,
            "created_at": target.get("created_at"),
            "last_login_at": target.get("last_login_at"),
            "login_count": target.get("login_count", 0),
        },
        "activity": db.get_user_activities(target["username"]),
    }


@router.patch("/profile")
def update_own_profile(req: ProfileUpdateRequest, current_user: Dict = Depends(get_current_user)):
    updated = db.update_user_profile(current_user["id"], display_name=req.display_name)
    db.add_activity(current_user["username"], "profile_updated", details=f"Обновлено ФИО: {req.display_name.strip()}")
    return updated


@router.patch("/profile/preferences")
def update_own_preferences(req: PreferencesUpdateRequest, current_user: Dict = Depends(get_current_user)):
    try:
        prefs = db.update_user_preferences(
            current_user["id"],
            theme=req.theme,
            ui_style=req.ui_style,
            accent=req.accent,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if prefs is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {"ok": True, "preferences": prefs}


@router.post("/profile/password")
def change_own_password(req: PasswordChangeRequest, current_user: Dict = Depends(get_current_user)):
    fresh = db.get_user_by_id(current_user["id"])
    if not fresh or not verify_password(req.current_password, fresh.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Текущий пароль неверен")
    db.update_user_profile(current_user["id"], password_hash=hash_password(req.new_password))
    db.add_activity(current_user["username"], "profile_updated", details="Пароль изменён")
    return {"ok": True}


@router.post("/profile/credentials")
def change_own_credentials(req: CredentialsChangeRequest, current_user: Dict = Depends(get_current_user)):
    fresh = db.get_user_by_id(current_user["id"])
    if not fresh or not verify_password(req.current_password, fresh.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Текущий пароль неверен")
    if req.new_password.strip().lower() == "admin":
        raise HTTPException(status_code=400, detail="Пароль не может быть 'admin'")
    if req.new_password == req.current_password:
        raise HTTPException(status_code=400, detail="Новый пароль должен отличаться от текущего")

    try:
        updated = db.update_user_credentials(
            current_user["id"],
            req.new_username,
            hash_password(req.new_password),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    old_raw = current_user.get("_raw_token")
    old_payload = current_user.get("_jwt_payload") or {}
    if old_raw:
        invalidate_session(old_raw)

    new_token = create_session(
        updated["id"],
        updated["username"],
        role=updated["role"],
        trusted=bool(old_payload.get("trusted", False)),
        device_id=old_payload.get("device_id"),
    )
    return {"ok": True, "token": new_token, "user": updated}


MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/profile/avatar")
async def upload_avatar(
    request: Request,
    filename: str = Query("avatar.png", min_length=1, max_length=255),
    current_user: Dict = Depends(get_current_user),
):
    ct = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not ct.startswith("image/"):
        raise HTTPException(status_code=400, detail="Допускаются только изображения")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        ext = mimetypes.guess_extension(ct) or ".png"

    os.makedirs(AVATARS_DIR, exist_ok=True)
    stored = f"u{current_user['id']}_{uuid.uuid4().hex[:10]}{ext}"
    path = os.path.join(AVATARS_DIR, stored)
    size = 0
    try:
        with open(path, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_AVATAR_SIZE:
                    raise HTTPException(status_code=413, detail="Аватар больше 5 МБ")
                f.write(chunk)
    except BaseException:
        if os.path.exists(path):
            os.remove(path)
        raise
    if size == 0:
        os.remove(path)
        raise HTTPException(status_code=400, detail="Пустой файл")

    old_avatar = current_user.get("avatar")
    if old_avatar:
        old_path = os.path.join(AVATARS_DIR, old_avatar)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    updated = db.update_user_profile(current_user["id"], avatar=stored)
    db.add_activity(current_user["username"], "profile_updated", details=f"Обновлён аватар ({filename})")
    return updated


@router.delete("/profile/avatar")
def delete_avatar(current_user: Dict = Depends(get_current_user)):
    old_avatar = current_user.get("avatar")
    if old_avatar:
        old_path = os.path.join(AVATARS_DIR, old_avatar)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
    updated = db.update_user_profile(current_user["id"], avatar=None)
    db.add_activity(current_user["username"], "profile_updated", details="Удалён аватар")
    return updated


@router.get("/users/{username}/avatar")
def get_user_avatar(username: str):
    u = db.get_user_by_username(username)
    if not u or not u.get("avatar"):
        raise HTTPException(status_code=404, detail="Аватар не найден")
    path = os.path.join(AVATARS_DIR, u["avatar"])
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Файл аватара не найден")
    return FileResponse(path)


@router.get("/profile/activity")
def get_own_activity(current_user: Dict = Depends(get_current_user)):
    return db.get_user_activities(current_user["username"])


@router.get("/profile/trusted-devices")
def list_trusted_devices(current_user: Dict = Depends(get_current_user)):
    jwt_payload = current_user.get("_jwt_payload") or {}
    cur_dev_id = jwt_payload.get("device_id")
    return [
        {**d, "is_current": (d.get("id") == cur_dev_id)}
        for d in db.get_trusted_devices(current_user["id"])
    ]


@router.delete("/profile/trusted-devices/{device_id}")
def revoke_trusted_device(device_id: str, current_user: Dict = Depends(get_current_user)):
    if not db.remove_trusted_device(current_user["id"], device_id):
        raise HTTPException(status_code=404, detail="Устройство не найдено")
    db.add_activity(current_user["username"], "profile_updated", details=f"Отозвано доверенное устройство ({device_id})")
    return {"ok": True}


@router.post("/profile/totp/setup")
def setup_totp(current_user: Dict = Depends(get_current_user)):
    secret = generate_totp_secret()
    db.set_totp_pending(current_user["id"], secret)
    uri = get_totp_uri(secret, current_user["username"])
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "qr_svg": make_qr_svg(uri),
    }


@router.post("/profile/totp/enable")
def enable_totp(req: TotpCodeRequest, current_user: Dict = Depends(get_current_user)):
    fresh = db.get_user_by_id(current_user["id"])
    secret = fresh.get("totp_pending_secret") if fresh else None
    if not secret:
        raise HTTPException(status_code=400, detail="Сначала запустите настройку TOTP")
    if not verify_totp(secret, req.code):
        raise HTTPException(status_code=400, detail="Неверный 6-значный код TOTP")
    db.enable_totp(current_user["id"], secret)
    db.add_activity(current_user["username"], "profile_updated", details="Включена двухфакторная аутентификация (TOTP)")
    return {"ok": True, "totp_enabled": True}


@router.post("/profile/totp/disable")
def disable_totp(req: TotpDisableRequest, current_user: Dict = Depends(get_current_user)):
    fresh = db.get_user_by_id(current_user["id"])
    if not fresh or not fresh.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="TOTP не включён")
    ok_pw = bool(req.password and verify_password(req.password, fresh.get("password_hash", "")))
    ok_code = bool(req.code and verify_totp(fresh.get("totp_secret"), req.code))
    if not (ok_pw or ok_code):
        raise HTTPException(status_code=400, detail="Укажите верный пароль или код TOTP для отключения")
    db.disable_totp(current_user["id"])
    db.add_activity(current_user["username"], "profile_updated", details="Отключена двухфакторная аутентификация (TOTP)")
    return {"ok": True, "totp_enabled": False}


@router.get("/profile/tokens")
def list_pats(current_user: Dict = Depends(get_current_user)):
    return db.get_pats(current_user["id"])


@router.post("/profile/tokens", status_code=201)
def create_pat(req: PatCreateRequest, current_user: Dict = Depends(get_current_user)):
    raw, prefix, token_hash = generate_pat_token()
    expires_at = (
        (datetime.utcnow() + timedelta(days=req.expires_days)).isoformat() + "Z"
        if req.expires_days else None
    )
    meta = db.create_pat(current_user["id"], req.name, prefix, token_hash, expires_at)
    db.add_activity(current_user["username"], "profile_updated", details=f"Создан персональный токен «{req.name.strip()}»")
    return {**meta, "token": raw}


@router.delete("/profile/tokens/{pat_id}")
def delete_pat(pat_id: str, current_user: Dict = Depends(get_current_user)):
    if not db.delete_pat(current_user["id"], pat_id):
        raise HTTPException(status_code=404, detail="Токен не найден")
    db.add_activity(current_user["username"], "profile_updated", details=f"Удалён персональный токен ({pat_id})")
    return {"ok": True}


# ============================================================================
# NOTIFICATIONS & ANALYTICS
# ============================================================================
@router.get("/notifications")
def list_notifications(current_user: Dict = Depends(get_current_user)):
    return db.get_notifications(current_user["username"])


@router.post("/notifications/{notif_id}/read")
def mark_notification_read(notif_id: int, current_user: Dict = Depends(get_current_user)):
    db.mark_notification_read(current_user["username"], notif_id)
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_notifications_read(current_user: Dict = Depends(get_current_user)):
    count = db.mark_all_notifications_read(current_user["username"])
    return {"ok": True, "marked": count}


@router.delete("/notifications/{notif_id}")
def delete_notification(notif_id: int, current_user: Dict = Depends(get_current_user)):
    ok = db.delete_notification(current_user["username"], notif_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    return {"ok": True}


@router.get("/analytics")
def get_analytics(
    days: Optional[int] = Query(None, ge=1, le=365),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    all_time: bool = Query(False),
    current_user: Dict = Depends(get_current_user),
):
    return db.get_analytics(days=days, date_from=date_from, date_to=date_to, all_time=all_time)


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
    task_type: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    epic_id: Optional[int] = Query(None),
    sirius_id: Optional[int] = Query(None),
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
        in_sprint=in_sprint,
        task_type=task_type,
        cluster=cluster,
        epic_id=epic_id,
        sirius_id=sirius_id,
    )
    return tasks


@router.post("/tasks", status_code=201)
def create_task(req: TaskCreateRequest, current_user: Dict = Depends(require_role("member"))):
    status_val = req.status if req.status in VALID_STATUSES else "Бэклог"
    ttype = req.task_type if req.task_type in VALID_TASK_TYPES else "Задача"
    cl = req.cluster if req.cluster in VALID_CLUSTERS else ""
    try:
        new_task = db.create_task(
            title=req.title,
            description=req.description or "",
            story_points=req.story_points,
            assignee=req.assignee,
            status=status_val,
            in_sprint=bool(req.in_sprint),
            created_by=current_user["username"],
            task_type=ttype,
            cluster=cl,
            epic_id=req.epic_id,
            sirius_id=req.sirius_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.add_activity(
        current_user["username"],
        "task_created",
        new_task["id"],
        new_task["key"],
        new_task["title"],
        f"Создана задача ({ttype}{', ' + cl if cl else ''})",
    )
    if new_task.get("assignee"):
        _notify_task_change(
            new_task,
            current_user["username"],
            "assigned",
            f"Назначена задача {new_task['key']}",
            f"{current_user['username']} назначил вам задачу: {new_task['title']}",
            [new_task["assignee"]],
        )
    return new_task


@router.post("/tasks/reorder")
def reorder_tasks(req: ReorderRequest, current_user: Dict = Depends(require_role("member"))):
    db.reorder_tasks(req.task_ids)
    db.add_activity(current_user["username"], "task_reordered", details=f"Обновлён порядок задач ({len(req.task_ids)} шт.)")
    return {"ok": True}


@router.post("/tasks/{task_id}/toggle-sprint")
def toggle_sprint(task_id: int, current_user: Dict = Depends(require_role("member"))):
    task = db.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    new_val = not bool(task.get("in_sprint", False))
    active = db.get_active_sprint()
    sprint_id = active["id"] if (new_val and active) else (None if not new_val else task.get("sprint_id"))
    updated = db.update_task(task_id, {"in_sprint": new_val, "sprint_id": sprint_id})
    db.add_activity(
        current_user["username"],
        "task_updated",
        task["id"],
        task["key"],
        task["title"],
        "Добавлена в спринт" if new_val else "Перенесена в бэклог",
    )
    return updated


@router.post("/tasks/{task_id}/next-sprint")
def toggle_next_sprint(task_id: int, current_user: Dict = Depends(require_role("member"))):
    task = db.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    planned = db.get_planned_sprint()
    if planned and task.get("sprint_id") == planned["id"] and not bool(task.get("in_sprint", False)):
        updated = db.update_task(task_id, {"in_sprint": False, "sprint_id": None})
        db.add_activity(
            current_user["username"],
            "task_updated",
            task["id"],
            task["key"],
            task["title"],
            f"Убрана из следующего спринта «{planned['name']}»",
        )
        return updated

    if not planned:
        planned = db.get_or_create_planned_sprint(created_by=current_user["username"])
    updated = db.update_task(task_id, {"in_sprint": False, "sprint_id": planned["id"]})
    db.add_activity(
        current_user["username"],
        "task_updated",
        task["id"],
        task["key"],
        task["title"],
        f"Добавлена в следующий спринт «{planned['name']}»",
    )
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


@router.get("/sprints/planned")
def get_planned_sprint(current_user: Dict = Depends(get_current_user)):
    return db.get_planned_sprint()


@router.post("/sprints", status_code=201)
def create_sprint(req: SprintCreateRequest, current_user: Dict = Depends(require_role("manager"))):
    eff_status = "planned" if (req.status or "active") == "planned" else "active"
    new_sprint = db.create_sprint(
        name=req.name,
        goal=req.goal or "",
        created_by=current_user["username"],
        status=eff_status,
    )
    action_label = "Запланирован спринт" if eff_status == "planned" else "Запущен спринт"
    db.add_activity(current_user["username"], "sprint_created", details=f"{action_label} «{new_sprint['name']}»")
    return new_sprint


@router.patch("/sprints/{sprint_id}")
def update_sprint(
    sprint_id: int,
    req: SprintUpdateRequest,
    current_user: Dict = Depends(require_role("manager")),
):
    prev = db.get_sprint_by_id(sprint_id)
    if not prev:
        raise HTTPException(status_code=404, detail="Спринт не найден")
    updated = db.update_sprint(sprint_id, name=req.name, goal=req.goal)
    if not updated:
        raise HTTPException(status_code=404, detail="Спринт не найден")
    db.add_activity(
        current_user["username"],
        "sprint_updated",
        details=f"Обновлён спринт: «{prev.get('name')}» → «{updated['name']}»",
    )
    return updated


@router.post("/sprints/{sprint_id}/close")
def close_sprint(
    sprint_id: int,
    req: Optional[SprintCloseRequest] = None,
    current_user: Dict = Depends(require_role("manager"))
):
    create_next = req.create_next_sprint if req else True
    next_name = req.next_sprint_name if req else None
    result = db.close_sprint(sprint_id, create_next_sprint=create_next, next_sprint_name=next_name)
    if not result:
        raise HTTPException(status_code=404, detail="Спринт не найден")
    db.add_activity(current_user["username"], "sprint_closed", details=f"Завершён спринт «{result['sprint']['name']}»")
    return result


@router.get("/tasks/{task_id}")
def get_task(task_id: int, current_user: Dict = Depends(get_current_user)):
    task = db.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    comments = db.get_comments(task_id)
    children = db.get_task_hierarchy_children(task_id)
    return {**task, "comments": comments, **children}


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int,
    req: TaskUpdateRequest,
    current_user: Dict = Depends(require_role("member"))
):
    prev = db.get_task_by_id(task_id)
    if not prev:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    updates = req.model_dump(exclude_unset=True)
    if "sprint_id" in updates:
        target_sid = updates["sprint_id"]
        if target_sid is None:
            updates["in_sprint"] = False
        else:
            target_sprint = db.get_sprint_by_id(target_sid)
            if target_sprint:
                updates["in_sprint"] = (target_sprint.get("status") == "active")
    elif "in_sprint" in updates:
        active = db.get_active_sprint()
        if updates["in_sprint"] and active:
            updates["sprint_id"] = active["id"]
        elif not updates["in_sprint"]:
            updates["sprint_id"] = None

    try:
        task = db.update_task(task_id, updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    actor = current_user["username"]
    if "status" in updates and updates["status"] != prev.get("status"):
        db.add_activity(actor, "task_status", task["id"], task["key"], task["title"],
                        f"Статус: {prev.get('status')} → {task['status']}")
        _notify_task_change(
            task, actor, "status",
            f"Статус {task['key']}: {task['status']}",
            f"{actor} изменил статус задачи {task['key']} ({task['title']}) на «{task['status']}»",
            [task.get("assignee"), task.get("created_by")],
        )
    if "assignee" in updates and updates["assignee"] != prev.get("assignee"):
        if task.get("assignee"):
            db.add_activity(actor, "task_assigned", task["id"], task["key"], task["title"],
                            f"Исполнитель: @{task['assignee']}")
            _notify_task_change(
                task, actor, "assigned",
                f"Назначена задача {task['key']}",
                f"{actor} назначил вам задачу: {task['title']}",
                [task["assignee"]],
            )
    if not any(k in updates for k in ("status", "assignee")):
        diffs = []
        if "title" in updates and task.get("title") != prev.get("title"):
            diffs.append(f"Название: «{prev.get('title')}» -> «{task.get('title')}»")
        if "story_points" in updates and task.get("story_points") != prev.get("story_points"):
            diffs.append(f"SP: {prev.get('story_points')} -> {task.get('story_points')}")
        if "task_type" in updates and task.get("task_type") != prev.get("task_type"):
            diffs.append(f"Подтип: {prev.get('task_type')} -> {task.get('task_type')}")
        if "epic_id" in updates and task.get("epic_id") != prev.get("epic_id"):
            diffs.append(f"Эпик: {prev.get('epic_key') or '—'} -> {task.get('epic_key') or '—'}")
        if "sirius_id" in updates and task.get("sirius_id") != prev.get("sirius_id"):
            diffs.append(f"Сириус: {prev.get('sirius_key') or '—'} -> {task.get('sirius_key') or '—'}")
        if "in_sprint" in updates and task.get("in_sprint") != prev.get("in_sprint"):
            diffs.append("Добавлена в спринт" if task.get("in_sprint") else "Убрана из спринта")
        if "description" in updates and task.get("description") != prev.get("description"):
            diffs.append("Изменено описание")
        detail_str = "; ".join(diffs) if diffs else "Обновлены параметры задачи"
        db.add_activity(actor, "task_updated", task["id"], task["key"], task["title"], detail_str)
    return task


@router.post("/tasks/{task_id}/take")
def take_task(task_id: int, current_user: Dict = Depends(require_role("member"))):
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
    db.add_activity(
        current_user["username"],
        "task_taken",
        updated["id"],
        updated["key"],
        updated["title"],
        "Взята в работу",
    )
    return updated


@router.post("/tasks/{task_id}/split-partial")
def split_partial_task(
    task_id: int,
    req: SplitPartialRequest,
    current_user: Dict = Depends(require_role("member"))
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
        parent_task_id=task_id,
        task_type=orig_task.get("task_type", "Задача"),
        cluster=orig_task.get("cluster", ""),
    )

    # Automatically add comment to original task referencing the new backlog task
    db.add_comment(
        task_id=task_id,
        author="Klukva",
        text=f"Нереализованная часть вынесена в бэклог: {new_task['key']} - {new_task['title']}",
        mentions=[]
    )
    db.add_activity(
        current_user["username"],
        "task_created",
        new_task["id"],
        new_task["key"],
        new_task["title"],
        f"Вынесена из {orig_task['key']}",
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
    current_user: Dict = Depends(require_role("member"))
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
    actor = current_user["username"]
    db.add_activity(actor, "comment_added", task["id"], task["key"], task["title"], req.text[:120])
    if mentions:
        _notify_task_change(
            task, actor, "mention",
            f"Упоминание в {task['key']}",
            f"@{actor} упомянул вас в {task['key']}: {req.text[:100]}",
            mentions,
        )
    # Notify assignee and creator if they weren't already mentioned
    other_targets = [t for t in [task.get("assignee"), task.get("created_by")]
                     if t and t.lower() not in {m.lower() for m in mentions}]
    if other_targets:
        _notify_task_change(
            task, actor, "comment",
            f"Комментарий в {task['key']}",
            f"@{actor} оставил комментарий: {req.text[:100]}",
            other_targets,
        )
    return comment


@router.patch("/tasks/{task_id}/comments/{comment_id}")
def update_comment(
    task_id: int,
    comment_id: int,
    req: CommentCreateRequest,
    current_user: Dict = Depends(require_role("member"))
):
    comment = db.get_comment_by_id(comment_id)
    if not comment or comment.get("task_id") != task_id:
        raise HTTPException(status_code=404, detail="Комментарий не найден")

    if comment["author"] != current_user["username"] and not has_min_role(current_user, "manager"):
        raise HTTPException(status_code=403, detail="Редактировать комментарий может только его автор")

    mentions = extract_mentions(req.text)
    updated = db.update_comment(comment_id, req.text, mentions)
    task = db.get_task_by_id(task_id)
    if task:
        db.add_activity(current_user["username"], "comment_updated", task["id"], task["key"], task["title"], req.text[:120])
    return updated


@router.delete("/tasks/{task_id}/comments/{comment_id}")
def delete_comment(
    task_id: int,
    comment_id: int,
    current_user: Dict = Depends(require_role("member"))
):
    comment = db.get_comment_by_id(comment_id)
    if not comment or comment.get("task_id") != task_id:
        raise HTTPException(status_code=404, detail="Комментарий не найден")

    if comment["author"] != current_user["username"] and not has_min_role(current_user, "manager"):
        raise HTTPException(status_code=403, detail="Удалять комментарий может только его автор")

    success = db.delete_comment(comment_id)
    task = db.get_task_by_id(task_id)
    if success and task:
        db.add_activity(current_user["username"], "comment_deleted", task["id"], task["key"], task["title"], "Удалён комментарий")
    return {"ok": success}


# ============================================================================
# TASK LINKS
# ============================================================================
class LinkCreateRequest(BaseModel):
    type: str
    target_id: int
    # "outward": current task is the source (blocks / parent of target)
    # "inward": current task is the target (blocked by / subtask of target)
    direction: str = "outward"


def _link_comment(task_id: int, other_id: int, label: str, removed: bool, user: str) -> None:
    other = db.get_task_by_id(other_id)
    if not other:
        return
    action = "удалил связь" if removed else "добавил связь"
    db.add_comment(
        task_id=task_id,
        author="Klukva",
        text=f"{user} {action}: {label} {other['key']} - {other['title']}",
        mentions=[]
    )


def _labels(link: Dict) -> tuple:
    from backend.db import LINK_LABELS
    return LINK_LABELS[link["type"]]


@router.get("/tasks/{task_id}/links")
def list_links(task_id: int, current_user: Dict = Depends(get_current_user)):
    if not db.get_task_by_id(task_id):
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return db.get_links(task_id)


@router.post("/tasks/{task_id}/links", status_code=201)
def create_link(task_id: int, req: LinkCreateRequest, current_user: Dict = Depends(require_role("member"))):
    if req.direction not in ("outward", "inward"):
        raise HTTPException(status_code=400, detail="Неверное направление связи")
    src, dst = (task_id, req.target_id) if req.direction == "outward" else (req.target_id, task_id)
    try:
        link = db.create_link(req.type, src, dst, current_user["username"])
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    out_label, in_label = _labels(link)
    _link_comment(src, dst, out_label, False, current_user["username"])
    _link_comment(dst, src, in_label, False, current_user["username"])
    src_t = db.get_task_by_id(src)
    dst_t = db.get_task_by_id(dst)
    if src_t and dst_t:
        db.add_activity(
            current_user["username"],
            "link_created",
            src_t["id"],
            src_t["key"],
            src_t["title"],
            f"Связь: {out_label} {dst_t['key']}",
        )
    return link


@router.delete("/tasks/{task_id}/links/{link_id}")
def delete_link(task_id: int, link_id: int, current_user: Dict = Depends(require_role("member"))):
    existing = [l for l in db.get_links(task_id) if l["id"] == link_id]
    if not existing:
        raise HTTPException(status_code=404, detail="Связь не найдена")
    link = db.delete_link(link_id)
    out_label, in_label = _labels(link)
    _link_comment(link["source_id"], link["target_id"], out_label, True, current_user["username"])
    _link_comment(link["target_id"], link["source_id"], in_label, True, current_user["username"])
    src_t = db.get_task_by_id(link["source_id"])
    dst_t = db.get_task_by_id(link["target_id"])
    if src_t and dst_t:
        db.add_activity(
            current_user["username"],
            "link_deleted",
            src_t["id"],
            src_t["key"],
            src_t["title"],
            f"Удалена связь: {out_label} {dst_t['key']}",
        )
    return {"ok": True}


# ============================================================================
# TASK ATTACHMENTS
# ============================================================================
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 20 MB


def _user_from_header_or_query(authorization: Optional[str], token: Optional[str]) -> Dict:
    raw = authorization or token
    if raw:
        parts = raw.split(" ")
        user = get_user_from_token(parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else raw)
        if user:
            if user.get("must_change_credentials"):
                raise HTTPException(
                    status_code=403,
                    detail="Необходимо принудительно изменить логин и пароль по умолчанию в профиле"
                )
            return user
    raise HTTPException(status_code=401, detail="Требуется авторизация")


@router.get("/tasks/{task_id}/attachments")
def list_attachments(task_id: int, current_user: Dict = Depends(get_current_user)):
    if not db.get_task_by_id(task_id):
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return db.get_attachments(task_id)


@router.post("/tasks/{task_id}/attachments", status_code=201)
async def upload_attachment(
    task_id: int,
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    current_user: Dict = Depends(require_role("member")),
):
    if not db.get_task_by_id(task_id):
        raise HTTPException(status_code=404, detail="Задача не найдена")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=413, detail="Файл больше 20 МБ")

    safe_name = os.path.basename(filename.replace("\\", "/")).strip() or "file"
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{os.path.splitext(safe_name)[1][:16]}"
    path = os.path.join(ATTACHMENTS_DIR, stored_name)
    size = 0
    try:
        with open(path, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_ATTACHMENT_SIZE:
                    raise HTTPException(status_code=413, detail="Файл больше 20 МБ")
                f.write(chunk)
    except BaseException:
        if os.path.exists(path):
            os.remove(path)
        raise
    if size == 0:
        os.remove(path)
        raise HTTPException(status_code=400, detail="Пустой файл")

    content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
    if not content_type or content_type == "application/octet-stream":
        content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    att = db.add_attachment(task_id, safe_name, stored_name, size, content_type, current_user["username"])
    task = db.get_task_by_id(task_id)
    db.add_comment(task_id=task_id, author="Klukva",
                   text=f"{current_user['username']} прикрепил файл: {safe_name}", mentions=[])
    if task:
        db.add_activity(
            current_user["username"],
            "attachment_uploaded",
            task["id"],
            task["key"],
            task["title"],
            f"Загружен файл: {safe_name} ({size} байт)",
        )
    return att


@router.get("/tasks/{task_id}/attachments/{att_id}/file")
def get_attachment_file(
    task_id: int,
    att_id: int,
    download: bool = False,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    _user_from_header_or_query(authorization, token)
    att = db.get_attachment(att_id)
    if not att or att["task_id"] != task_id:
        raise HTTPException(status_code=404, detail="Файл не найден")
    path = os.path.join(ATTACHMENTS_DIR, att["stored_name"])
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Файл отсутствует на диске")
    return FileResponse(
        path,
        media_type=att["content_type"],
        filename=att["filename"],
        content_disposition_type="attachment" if download else "inline",
    )


@router.delete("/tasks/{task_id}/attachments/{att_id}")
def delete_attachment(task_id: int, att_id: int, current_user: Dict = Depends(require_role("member"))):
    att = db.get_attachment(att_id)
    if not att or att["task_id"] != task_id:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if att.get("uploaded_by") != current_user["username"] and not has_min_role(current_user, "manager"):
        raise HTTPException(status_code=403, detail="Удалять файл может автор или менеджер")
    db.delete_attachment(att_id)
    path = os.path.join(ATTACHMENTS_DIR, att["stored_name"])
    if os.path.exists(path):
        os.remove(path)
    task = db.get_task_by_id(task_id)
    db.add_comment(task_id=task_id, author="Klukva",
                   text=f"{current_user['username']} удалил файл: {att['filename']}", mentions=[])
    if task:
        db.add_activity(
            current_user["username"],
            "attachment_deleted",
            task["id"],
            task["key"],
            task["title"],
            f"Удалён файл: {att['filename']}",
        )
    return {"ok": True}


# ============================================================================
# SYSTEM / UPDATE
# ============================================================================
DEFAULT_GITHUB_REPO = "SL1dee36/klukva"
DEFAULT_GITHUB_BRANCH = "main"
VERSION_META_FILE = ".klukva_version.json"
UPDATE_TOKEN_FILE = ".klukva_update_token"
PROTECTED_TOP_ENTRIES = {
    "klukva_db.json",
    "klukva_attachments",
    "klukva_backups",
    ".git",
    ".venv",
    "venv",
    ".env",
    "__pycache__",
    "logs",
    VERSION_META_FILE,
    UPDATE_TOKEN_FILE,
}


class SystemUpdateRequest(BaseModel):
    github_token: Optional[str] = None
    save_token: Optional[bool] = False


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


def _get_github_repo_and_branch() -> tuple[str, str]:
    repo = (os.environ.get("KLUKVA_GITHUB_REPO") or DEFAULT_GITHUB_REPO).strip()
    branch = (os.environ.get("KLUKVA_GITHUB_BRANCH") or DEFAULT_GITHUB_BRANCH).strip()
    return repo, branch


def _get_github_token(repo_dir: str, explicit_token: Optional[str] = None) -> str:
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()
    env_tok = (os.environ.get("KLUKVA_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if env_tok:
        return env_tok
    tok_path = os.path.join(repo_dir, UPDATE_TOKEN_FILE)
    if os.path.exists(tok_path):
        try:
            with open(tok_path, "r", encoding="utf-8") as f:
                saved = f.read().strip()
                if saved:
                    return saved
        except Exception:
            pass
    git_cfg = os.path.join(repo_dir, ".git", "config")
    if os.path.exists(git_cfg):
        try:
            with open(git_cfg, "r", encoding="utf-8", errors="ignore") as f:
                m = re.search(r"https://([^@\s/]+)@github\.com/", f.read())
                if m:
                    raw = m.group(1)
                    return raw.split(":")[-1] if ":" in raw else raw
        except Exception:
            pass
    return ""


def _save_github_token(repo_dir: str, token: str) -> None:
    tok_path = os.path.join(repo_dir, UPDATE_TOKEN_FILE)
    with open(tok_path, "w", encoding="utf-8") as f:
        f.write(token.strip())
    try:
        os.chmod(tok_path, 0o600)
    except Exception:
        pass


def _read_version_meta(repo_dir: str) -> Optional[Dict[str, Any]]:
    meta_path = os.path.join(repo_dir, VERSION_META_FILE)
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and data.get("sha"):
                return data
    except Exception:
        pass
    return None


def _write_version_meta(repo_dir: str, info: Dict[str, Any]) -> None:
    meta_path = os.path.join(repo_dir, VERSION_META_FILE)
    payload = {
        "sha": info.get("sha"),
        "short_sha": info.get("short_sha") or (info.get("sha") or "")[:7],
        "date": info.get("date"),
        "message": info.get("message"),
        "repo": info.get("repo"),
        "branch": info.get("branch"),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_app_version(repo_dir: str) -> str:
    ver_file = os.path.join(repo_dir, "VERSION")
    if os.path.exists(ver_file):
        try:
            with open(ver_file, "r", encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    return v
        except Exception:
            pass
    return "2.4.1"


def _get_local_version_info(repo_dir: str) -> Dict[str, Any]:
    app_ver = _get_app_version(repo_dir)
    git_dir = os.path.join(repo_dir, ".git")
    if os.path.exists(git_dir):
        try:
            res = subprocess.run(
                ["git", "log", "-1", "--format=%H%n%h%n%cI%n%s"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=8,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0:
                lines = (res.stdout or "").splitlines()
                if len(lines) >= 2:
                    return {
                        "app_version": app_ver,
                        "sha": lines[0].strip(),
                        "short_sha": lines[1].strip(),
                        "date": lines[2].strip() if len(lines) > 2 else None,
                        "message": lines[3].strip() if len(lines) > 3 else "",
                        "source": "git",
                    }
        except Exception:
            pass

    meta = _read_version_meta(repo_dir)
    if meta:
        return {
            "app_version": meta.get("app_version") or app_ver,
            "sha": meta.get("sha"),
            "short_sha": meta.get("short_sha") or (meta.get("sha") or "")[:7],
            "date": meta.get("date"),
            "message": meta.get("message") or "",
            "updated_at": meta.get("updated_at"),
            "source": "meta",
        }

    return {
        "app_version": app_ver,
        "sha": None,
        "short_sha": None,
        "date": None,
        "message": "",
        "source": "version_file",
    }


def _fetch_remote_github_version(repo: str, branch: str, token: str = "") -> Dict[str, Any]:
    url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Klukva-Updater/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            sha = data.get("sha") or ""
            commit = data.get("commit") or {}
            committer = commit.get("committer") or commit.get("author") or {}
            msg_first_line = (commit.get("message") or "").splitlines()[0] if commit.get("message") else ""
            return {
                "ok": True,
                "sha": sha,
                "short_sha": sha[:7] if sha else "",
                "date": committer.get("date"),
                "message": msg_first_line,
                "url": data.get("html_url"),
                "repo": repo,
                "branch": branch,
            }
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return {
                "ok": False,
                "auth_required": True,
                "error": f"GitHub API вернул {e.code}. Если репозиторий приватный, укажите GitHub PAT в настройках обновления.",
            }
        return {"ok": False, "error": f"Ошибка GitHub API: HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": f"Не удалось подключиться к GitHub: {e}"}


def _is_protected_rel_path(rel_path: str, repo_dir: str) -> bool:
    norm = rel_path.replace("\\", "/").lstrip("/")
    if not norm:
        return True
    parts = norm.split("/")
    top = parts[0]
    if top in PROTECTED_TOP_ENTRIES:
        return True
    if top.startswith("klukva_db.json") or top.endswith(".db") or top.startswith(".env"):
        return True
    if "__pycache__" in parts:
        return True
    abs_target = os.path.abspath(os.path.join(repo_dir, norm))
    db_abs = os.path.abspath(DB_FILE_PATH)
    att_abs = os.path.abspath(ATTACHMENTS_DIR)
    if abs_target == db_abs or abs_target.startswith(att_abs + os.sep) or abs_target == att_abs:
        return True
    return False


def _update_from_github_archive(
    repo_dir: str,
    repo: str,
    branch: str,
    token: str = "",
    latest_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not latest_info or not latest_info.get("ok"):
        latest_info = _fetch_remote_github_version(repo, branch, token=token)
        if not latest_info.get("ok"):
            return latest_info

    local_before = _get_local_version_info(repo_dir)
    zip_url = f"https://api.github.com/repos/{repo}/zipball/{branch}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Klukva-Updater/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with tempfile.TemporaryDirectory(prefix="klukva_upd_") as tmpdir:
            zip_path = os.path.join(tmpdir, "repo.zip")
            req = urllib.request.Request(zip_url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out_f:
                shutil.copyfileobj(resp, out_f)

            extract_dir = os.path.join(tmpdir, "extracted")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            entries = [os.path.join(extract_dir, name) for name in os.listdir(extract_dir)]
            dirs = [p for p in entries if os.path.isdir(p)]
            src_root = dirs[0] if len(dirs) == 1 else extract_dir

            updated_files: List[str] = []
            py_changed = False

            for root, dirnames, filenames in os.walk(src_root):
                rel_dir = os.path.relpath(root, src_root)
                if rel_dir == ".":
                    rel_dir = ""

                # Prune protected directories
                dirnames[:] = [
                    d for d in dirnames
                    if not _is_protected_rel_path(os.path.join(rel_dir, d) if rel_dir else d, repo_dir)
                ]

                for fname in filenames:
                    rel_file = os.path.join(rel_dir, fname) if rel_dir else fname
                    if _is_protected_rel_path(rel_file, repo_dir):
                        continue

                    src_file = os.path.join(root, fname)
                    dst_file = os.path.join(repo_dir, rel_file)

                    with open(src_file, "rb") as sf:
                        new_bytes = sf.read()

                    old_bytes = None
                    if os.path.exists(dst_file):
                        try:
                            with open(dst_file, "rb") as df:
                                old_bytes = df.read()
                        except Exception:
                            old_bytes = None

                    if old_bytes != new_bytes:
                        os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                        with open(dst_file, "wb") as df:
                            df.write(new_bytes)
                        updated_files.append(rel_file.replace("\\", "/"))
                        if rel_file.endswith(".py"):
                            py_changed = True

        _write_version_meta(repo_dir, latest_info)
        local_after = _get_local_version_info(repo_dir)
        is_updated = bool(updated_files) or (local_before.get("sha") != latest_info.get("sha"))

        return {
            "ok": True,
            "mode": "github_archive",
            "updated": is_updated,
            "updated_files_count": len(updated_files),
            "py_changed": py_changed,
            "current": local_after,
            "latest": latest_info,
            "message": (
                f"Обновлено файлов: {len(updated_files)} (версия {latest_info.get('short_sha')}). БД и вложения сохранены."
                if is_updated
                else "Установлена актуальная версия."
            ),
        }
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return {
                "ok": False,
                "auth_required": True,
                "error": f"Не удалось скачать архив с GitHub (HTTP {e.code}). Проверьте GitHub PAT.",
            }
        return {"ok": False, "error": f"Ошибка скачивания архива с GitHub: HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": f"Ошибка обновления из GitHub: {e}"}


def pull_repo_changes(repo_dir: str, token: str = "") -> Dict[str, Any]:
    repo, branch = _get_github_repo_and_branch()
    eff_token = _get_github_token(repo_dir, explicit_token=token)
    git_dir = os.path.join(repo_dir, ".git")

    has_git = False
    if os.path.exists(git_dir):
        try:
            check_git = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
            has_git = (check_git.returncode == 0)
        except Exception:
            has_git = False

    if not has_git:
        # Server deployment without .git (e.g. /opt/klukva): update directly via GitHub archive
        return _update_from_github_archive(repo_dir, repo, branch, token=eff_token)

    try:
        res = subprocess.run(
            ["git", "pull", "--autostash", "origin", branch],
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
        local_after = _get_local_version_info(repo_dir)
        if local_after.get("sha"):
            _write_version_meta(repo_dir, {**local_after, "repo": repo, "branch": branch})

        return {
            "ok": True,
            "mode": "git",
            "updated": is_updated,
            "py_changed": py_changed,
            "current": local_after,
            "latest": local_after,
            "message": stdout or "Успешно обновлено",
            "output": stdout
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }


@router.get("/system/update/check")
def check_update_status(
    github_token: Optional[str] = Query(None),
    current_user: Dict = Depends(require_role("admin")),
):
    """Checks current local version vs latest commit on GitHub."""
    repo_dir = find_repo_dir()
    repo, branch = _get_github_repo_and_branch()
    eff_token = _get_github_token(repo_dir, explicit_token=github_token)
    mode = "git" if os.path.exists(os.path.join(repo_dir, ".git")) else "github_archive"

    local_info = _get_local_version_info(repo_dir)
    remote_info = _fetch_remote_github_version(repo, branch, token=eff_token)

    if not remote_info.get("ok"):
        return {
            "ok": False,
            "repo": repo,
            "branch": branch,
            "mode": mode,
            "current": local_info,
            "latest": None,
            "update_available": False,
            "has_token": bool(eff_token),
            "auth_required": bool(remote_info.get("auth_required")),
            "error": remote_info.get("error", "Ошибка проверки версии на GitHub"),
        }

    local_sha = local_info.get("sha")
    remote_sha = remote_info.get("sha")
    update_available = (not local_sha) or (bool(remote_sha) and local_sha != remote_sha)

    return {
        "ok": True,
        "repo": repo,
        "branch": branch,
        "mode": mode,
        "current": local_info,
        "latest": remote_info,
        "update_available": update_available,
        "has_token": bool(eff_token),
    }


def _schedule_process_restart(delay_sec: float = 0.8) -> None:
    """Exit process shortly after returning HTTP response so systemd restarts the service."""
    t = threading.Timer(delay_sec, lambda: os._exit(0))
    t.daemon = True
    t.start()


@router.post("/system/restart")
def restart_server(current_user: Dict = Depends(require_role("admin"))):
    """Schedules graceful process exit so systemd/supervisor restarts the backend."""
    db.add_activity(current_user["username"], "system_restart", details="Инициирован перезапуск сервера из UI")
    _schedule_process_restart(0.8)
    return {"ok": True, "restarting": True}


class SystemSettingsUpdateRequest(BaseModel):
    tempo_enabled: Optional[bool] = None
    tempo_daily_hours: Optional[int] = Field(None, ge=1, le=24)
    tempo_workdays: Optional[int] = Field(None, ge=1, le=7)


class WorklogCreateRequest(BaseModel):
    minutes: int = Field(..., ge=1, le=10080)
    work_date: Optional[str] = None
    comment: Optional[str] = ""


@router.get("/system/settings")
def get_system_settings(current_user: Dict = Depends(get_current_user)):
    return db.get_system_settings()


@router.patch("/system/settings")
def update_system_settings(
    req: SystemSettingsUpdateRequest,
    current_user: Dict = Depends(require_role("admin")),
):
    updates = req.model_dump(exclude_unset=True)
    res = db.update_system_settings(updates)
    if "tempo_enabled" in updates:
        state_lbl = "включён" if res["tempo_enabled"] else "выключен"
        db.add_activity(current_user["username"], "system_settings", details=f"Модуль Tempo {state_lbl}")
    return res


@router.get("/tasks/{task_id}/worklogs")
def list_task_worklogs(task_id: int, current_user: Dict = Depends(get_current_user)):
    if not db.get_system_settings().get("tempo_enabled"):
        raise HTTPException(status_code=403, detail="Модуль Tempo отключён администратором")
    return db.get_worklogs(task_id=task_id)


@router.post("/tasks/{task_id}/worklogs", status_code=201)
def create_task_worklog(
    task_id: int,
    req: WorklogCreateRequest,
    current_user: Dict = Depends(require_role("member")),
):
    if not db.get_system_settings().get("tempo_enabled"):
        raise HTTPException(status_code=403, detail="Модуль Tempo отключён администратором")
    try:
        entry = db.add_worklog(
            task_id=task_id,
            username=current_user["username"],
            minutes=req.minutes,
            comment=req.comment or "",
            work_date=req.work_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.add_activity(
        current_user["username"],
        "worklog_added",
        task_id,
        entry["task_key"],
        entry["task_title"],
        f"Списано время: {req.minutes} мин.",
    )
    return entry


@router.delete("/worklogs/{worklog_id}")
def delete_task_worklog(worklog_id: int, current_user: Dict = Depends(require_role("member"))):
    if not db.get_system_settings().get("tempo_enabled"):
        raise HTTPException(status_code=403, detail="Модуль Tempo отключён администратором")
    try:
        deleted = db.delete_worklog(
            worklog_id,
            actor_username=current_user["username"],
            is_manager=has_min_role(current_user, "manager"),
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Запись времени не найдена")
    return {"ok": True}


@router.get("/tempo/worklogs")
def get_tempo_timesheet(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    current_user: Dict = Depends(get_current_user),
):
    if not db.get_system_settings().get("tempo_enabled"):
        raise HTTPException(status_code=403, detail="Модуль Tempo отключён администратором")
    return db.get_tempo_summary(date_from=date_from, date_to=date_to, username=username)


@router.get("/system/backups")
def list_system_backups(current_user: Dict = Depends(require_role("admin"))):
    return db.list_backups()


@router.post("/system/backups")
def create_system_backup(current_user: Dict = Depends(require_role("admin"))):
    b = db.create_backup(reason="manual", keep=10)
    if not b:
        raise HTTPException(status_code=500, detail="Не удалось создать резервную копию БД")
    db.add_activity(current_user["username"], "system_backup", details=f"Создана резервная копия БД: {b['filename']}")
    return b


@router.post("/system/update")
def trigger_update(
    req: Optional[SystemUpdateRequest] = None,
    current_user: Dict = Depends(require_role("admin")),
):
    """Updates app from Git or GitHub archive while preserving DB and user data."""
    repo_dir = find_repo_dir()
    token = (req.github_token or "").strip() if req and req.github_token else ""
    if req and req.save_token and token:
        _save_github_token(repo_dir, token)

    backup_info = None
    try:
        backup_info = db.create_backup(reason="pre_update", keep=10)
    except Exception:
        pass

    res = pull_repo_changes(repo_dir, token=token)
    if backup_info:
        res["backup_file"] = backup_info.get("filename")
    db.add_activity(
        current_user["username"],
        "system_update",
        details=(
            f"Выполнено обновление ({res.get('mode', 'git')})"
            if res.get("ok")
            else f"Ошибка обновления: {res.get('error', '')}"
        ),
    )
    if res.get("ok") and res.get("updated") and res.get("py_changed") and not getattr(sys, "frozen", False):
        _schedule_process_restart(0.8)
        res["restarting"] = True
    return res


@router.get("/system/audit")
def get_system_audit(
    username: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(250, ge=1, le=1000),
    current_user: Dict = Depends(require_system_user()),
):
    return db.get_all_activities(username=username, action=action, search=search, limit=limit)


@router.get("/system/files")
def list_all_system_files(current_user: Dict = Depends(require_system_user())):
    attachments = db.get_all_attachments()
    enriched_atts = []
    total_size = 0
    for a in attachments:
        path = os.path.join(ATTACHMENTS_DIR, a["stored_name"])
        exists = os.path.exists(path)
        size = a.get("size", 0)
        total_size += size
        enriched_atts.append({
            **a,
            "kind": "attachment",
            "exists_on_disk": exists,
            "file_url": f"/api/tasks/{a['task_id']}/attachments/{a['id']}/file",
        })

    avatars = []
    for u in db.get_system_users_summary():
        if u.get("avatar_url"):
            # Look up exact stored filename from raw user record
            raw_u = db.get_user_by_id(u["id"])
            stored = raw_u.get("avatar") if raw_u else None
            if stored:
                apath = os.path.join(AVATARS_DIR, stored)
                exists = os.path.exists(apath)
                sz = os.path.getsize(apath) if exists else 0
                total_size += sz
                avatars.append({
                    "user_id": u["id"],
                    "username": u["username"],
                    "display_name": u["display_name"],
                    "stored_name": stored,
                    "size": sz,
                    "exists_on_disk": exists,
                    "file_url": u["avatar_url"],
                })

    return {
        "attachments": enriched_atts,
        "avatars": avatars,
        "total_files": len(enriched_atts) + len(avatars),
        "total_size": total_size,
    }


@router.get("/system/users")
def list_system_users(current_user: Dict = Depends(require_system_user())):
    return db.get_system_users_summary()


@router.post("/system/users/{user_id}/reset-totp")
def system_reset_user_totp(user_id: int, current_user: Dict = Depends(require_system_user())):
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    db.disable_totp(user_id)
    db.add_activity(
        current_user["username"],
        "system_security",
        details=f"Системный администратор отключил 2FA для @{target['username']}",
    )
    return {"ok": True}


@router.delete("/system/users/{user_id}/devices")
def system_clear_user_devices(user_id: int, current_user: Dict = Depends(require_system_user())):
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    count = db.clear_user_trusted_devices(user_id)
    db.add_activity(
        current_user["username"],
        "system_security",
        details=f"Сброшены доверенные устройства @{target['username']} ({count} шт.)",
    )
    return {"ok": True, "cleared": count}


@router.get("/system/db-export")
def system_export_db(current_user: Dict = Depends(require_system_user())):
    snapshot = db.export_snapshot()
    db.add_activity(current_user["username"], "system_db_exported", details="Выгружена резервная копия БД")
    return JSONResponse(
        content=snapshot,
        headers={"Content-Disposition": 'attachment; filename="klukva_db_backup.json"'},
    )

