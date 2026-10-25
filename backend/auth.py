"""
Authentication and session management for Klukva.
Uses standard library hashlib with pbkdf2_hmac for secure hashing with zero overhead.
"""

import hashlib
import hmac
import os
import secrets
import time
from typing import Dict, Optional
from fastapi import Header, HTTPException, status
from backend.db import db

# In-memory sessions table: token -> {user_id, username, created_at}
# Very fast, minimal memory (<100KB)
_active_sessions: Dict[str, Dict[str, str]] = {}
SESSION_EXPIRY_SECONDS = 60 * 60 * 24 * 30  # 30 days


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


def create_session(user_id: int, username: str) -> str:
    """Generate session token."""
    token = secrets.token_hex(32)
    _active_sessions[token] = {
        "user_id": user_id,
        "username": username,
        "created_at": time.time()
    }
    return token


def invalidate_session(token: str) -> None:
    _active_sessions.pop(token, None)


def get_user_from_token(token: str) -> Optional[Dict]:
    session = _active_sessions.get(token)
    if not session:
        return None
    # Check expiry
    if time.time() - session["created_at"] > SESSION_EXPIRY_SECONDS:
        _active_sessions.pop(token, None)
        return None
    user = db.get_user_by_id(session["user_id"])
    return user


async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict:
    """FastAPI dependency to extract and validate current authenticated user."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация"
        )
    parts = authorization.split(" ")
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1]
    else:
        token = authorization

    user = get_user_from_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия недействительна или истекла"
        )
    return user


async def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[Dict]:
    """Optional user dependency."""
    if not authorization:
        return None
    parts = authorization.split(" ")
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else authorization
    return get_user_from_token(token)
