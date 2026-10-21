"""Kimlik doğrulama ve yetkilendirme.

Şimdilik yerel kullanıcı + parola (PBKDF2). Active Directory / LDAP ya da Entra ID SSO
eklenmek istenirse `authenticate` fonksiyonu tek giriş noktasıdır.
"""
import hashlib
import hmac
import secrets
import time
from collections import defaultdict

from fastapi import HTTPException, Request

from . import db
from .domain import CAN_EDIT, CAN_UPLOAD, INTERNAL

_ITER = 260_000
_failed: dict[str, list[float]] = defaultdict(list)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITER).hex()
    return f"pbkdf2${_ITER}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters)).hex()
    return hmac.compare_digest(check, digest)


def too_many_attempts(key: str) -> bool:
    window = time.time() - 15 * 60
    _failed[key] = [t for t in _failed[key] if t > window]
    return len(_failed[key]) >= 8


def authenticate(email: str, password: str) -> dict | None:
    key = email.lower().strip()
    if too_many_attempts(key):
        return None
    user = db.row("SELECT * FROM users WHERE lower(email) = ? AND active = 1", (key,))
    if not user or not verify_password(password, user["password_hash"]):
        _failed[key].append(time.time())
        return None
    _failed.pop(key, None)
    db.execute("UPDATE users SET last_login = ? WHERE id = ?", (db.now(), user["id"]))
    return user


def current_user(request: Request) -> dict | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    return db.row("SELECT * FROM users WHERE id = ? AND active = 1", (uid,))


class LoginRequired(Exception):
    pass


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise LoginRequired()
    request.state.user = user
    return user


def require_internal(request: Request) -> dict:
    user = require_user(request)
    if user["role"] not in INTERNAL:
        raise HTTPException(403, "Bu alan yalnızca Doğuş Otomotiv kullanıcılarına açıktır.")
    return user


def require_editor(request: Request) -> dict:
    user = require_user(request)
    if user["role"] not in CAN_EDIT:
        raise HTTPException(403, "Bu işlem için düzenleme yetkisi gerekir.")
    return user


def require_uploader(request: Request) -> dict:
    user = require_user(request)
    if user["role"] not in CAN_UPLOAD:
        raise HTTPException(403, "Bu işlem için yükleme yetkisi gerekir.")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Bu alan yalnızca yöneticilere açıktır.")
    return user


def can_see_project(user: dict, project: dict) -> bool:
    return user["role"] != "dt" or bool(project.get("visible_to_dt"))
