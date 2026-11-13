"""
Authentication, JWT, TOTP (2FA), Trusted Devices, Personal Access Tokens, and RBAC for Klukva.
Uses Python standard library only (zero external dependencies).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
import urllib.parse
from typing import Any, Callable, Dict, Optional
from fastapi import Depends, Header, HTTPException, Request, status

from backend.db import ROLE_HIERARCHY, db

JWT_DEFAULT_TTL = 60 * 60 * 24 * 7       # 7 days for standard sessions
JWT_TRUSTED_TTL = 60 * 60 * 24 * 90      # 90 days for trusted devices
JWT_TOTP_CHALLENGE_TTL = 60 * 5          # 5 minutes for 2FA step

# Throttle updating trusted device last_used_at to avoid excessive writes
_device_touch_cache: Dict[str, float] = {}


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with random salt."""
    if not salt:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()
    return f"{salt}:{pw_hash}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored salt:hash string."""
    try:
        salt, pw_hash = stored_hash.split(":", 1)
        check_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100000
        ).hex()
        return hmac.compare_digest(pw_hash, check_hash)
    except Exception:
        return False


# ------------------ JWT (HS256) ------------------
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _get_jwt_secret() -> bytes:
    env_secret = os.environ.get("KLUKVA_JWT_SECRET")
    if env_secret:
        return env_secret.encode("utf-8")
    return db.get_or_create_jwt_secret().encode("utf-8")


def create_jwt(
    user_id: int,
    username: str,
    role: str = "member",
    trusted: bool = False,
    device_id: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
    scope: str = "access",
) -> str:
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else (JWT_TRUSTED_TTL if trusted else JWT_DEFAULT_TTL)
    header = {"alg": "HS256", "typ": "JWT"}
    payload: Dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "role": role,
        "scope": scope,
        "trusted": bool(trusted),
        "jti": secrets.token_hex(16),
        "iat": now,
        "exp": now + ttl,
    }
    if device_id:
        payload["device_id"] = device_id

    h_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = hmac.new(_get_jwt_secret(), signing_input, hashlib.sha256).digest()
    return f"{h_b64}.{p_b64}.{_b64url_encode(sig)}"


def decode_jwt(token: str, expected_scope: str = "access") -> Optional[Dict[str, Any]]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h_b64, p_b64, s_b64 = parts
        signing_input = f"{h_b64}.{p_b64}".encode("ascii")
        expected_sig = hmac.new(_get_jwt_secret(), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(s_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_b64url_decode(p_b64).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        if payload.get("scope", "access") != expected_scope:
            return None
        jti = payload.get("jti")
        if jti and db.is_jti_revoked(jti):
            return None
        return payload
    except Exception:
        return None


def create_session(
    user_id: int,
    username: str,
    role: str = "member",
    trusted: bool = False,
    device_id: Optional[str] = None,
) -> str:
    """Create a persistent signed JWT session token."""
    return create_jwt(user_id=user_id, username=username, role=role, trusted=trusted, device_id=device_id)


def invalidate_session(token: str) -> None:
    payload = decode_jwt(token)
    if payload and payload.get("jti"):
        db.revoke_jti(payload["jti"], int(payload.get("exp", time.time() + 3600)))


# ------------------ PERSONAL ACCESS TOKENS ------------------
def generate_pat_token() -> tuple[str, str, str]:
    """Return (raw_token, prefix, sha256_hash)."""
    raw = "klk_" + secrets.token_urlsafe(32)
    prefix = raw[:12]
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, prefix, token_hash


def hash_pat_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# ------------------ TOTP (RFC 6238) ------------------
def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def get_totp_uri(secret: str, username: str, issuer: str = "Klukva") -> str:
    label = urllib.parse.quote(f"{issuer}:{username}")
    params = urllib.parse.urlencode({
        "secret": secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": "6",
        "period": "30",
    })
    return f"otpauth://totp/{label}?{params}"


def _totp_at(secret: str, counter: int) -> str:
    s = secret.strip().upper().replace(" ", "")
    padding = "=" * (-len(s) % 8)
    key = base64.b32decode(s + padding)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code_int:06d}"


def verify_totp(secret: Optional[str], code: str, window: int = 1) -> bool:
    if not secret or not code:
        return False
    clean = code.strip().replace(" ", "")
    if not clean.isdigit() or len(clean) != 6:
        return False
    step = int(time.time() // 30)
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_totp_at(secret, step + delta), clean):
            return True
    return False


# ------------------ DEVICE PARSING ------------------
def parse_device_name(user_agent: str, custom_name: Optional[str] = None) -> str:
    if custom_name and custom_name.strip():
        return custom_name.strip()[:80]
    ua = user_agent or ""
    browser = "Браузер"
    if "Edg/" in ua or "EdgA/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Chrome/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua and "Chrome" not in ua:
        browser = "Safari"
    elif "pywebview" in ua.lower():
        browser = "Klukva Desktop"

    os_name = "Неизвестная ОС"
    if "Windows" in ua:
        os_name = "Windows"
    elif "Macintosh" in ua or "Mac OS" in ua:
        os_name = "macOS"
    elif "Android" in ua:
        os_name = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        os_name = "iOS"
    elif "Linux" in ua:
        os_name = "Linux"

    return f"{browser} · {os_name}"


# ------------------ TOKEN RESOLUTION & DEPENDENCIES ------------------
def get_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    if token.startswith("klk_"):
        user = db.find_user_by_pat_hash(hash_pat_token(token))
        if user:
            user = dict(user)
            user["_auth_type"] = "pat"
            return user
        return None

    payload = decode_jwt(token, expected_scope="access")
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.get_user_by_id(int(user_id))
    if not user:
        return None

    device_id = payload.get("device_id")
    if device_id:
        if not db.is_trusted_device_active(user["id"], device_id):
            return None
        now = time.time()
        last_touch = _device_touch_cache.get(device_id, 0.0)
        if now - last_touch > 300:
            _device_touch_cache[device_id] = now
            db.touch_trusted_device(user["id"], device_id)

    user = dict(user)
    user["_auth_type"] = "jwt"
    user["_jwt_payload"] = payload
    user["_raw_token"] = token
    return user


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


_ONBOARDING_ALLOWED_ROUTES = {
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/profile"),
    ("POST", "/api/profile/credentials"),
}


async def get_current_user(request: Request, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """FastAPI dependency to extract and validate current authenticated user (JWT or PAT)."""
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация"
        )
    user = get_user_from_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия недействительна или истекла"
        )
    if user.get("must_change_credentials"):
        key = (request.method.upper(), request.url.path)
        if key not in _ONBOARDING_ALLOWED_ROUTES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Необходимо принудительно изменить логин и пароль по умолчанию в профиле"
            )
    return user


async def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    token = _extract_bearer(authorization)
    if not token:
        return None
    return get_user_from_token(token)


def has_min_role(user: Dict[str, Any], min_role: str) -> bool:
    if user.get("is_system"):
        return True
    user_level = ROLE_HIERARCHY.get(user.get("role", "member"), 1)
    req_level = ROLE_HIERARCHY.get(min_role, 1)
    return user_level >= req_level


def require_role(min_role: str) -> Callable:
    async def _checker(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if not has_min_role(current_user, min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Недостаточно прав (требуется роль не ниже '{min_role}')"
            )
        return current_user
    return _checker


def require_system_user() -> Callable:
    async def _checker(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if not current_user.get("is_system"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступно только системному пользователю"
            )
        return current_user
    return _checker
