"""
Portal auth. Two principals:
  * employees  - native accounts here (PBKDF2 password hash + portal JWT),
  * admins     - NOT stored here; verified by delegating the login to
                 PhishAwareness, then issued a short-lived portal admin JWT.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app import models as m

_ALG = "HS256"
_ROUNDS = 200_000


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _ROUNDS)
    return "pbkdf2$%d$%s$%s" % (
        _ROUNDS, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, rounds, b64salt, b64dk = stored.split("$")
        salt = base64.b64decode(b64salt)
        expected = base64.b64decode(b64dk)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _make_token(sub: str, kind: str, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub, "kind": kind, "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALG)


def make_employee_token(user) -> str:
    return _make_token(user.id, "employee", {"email": user.email})


def make_admin_token(email: str, tenant_id: str | None, role: str) -> str:
    return _make_token(email, "admin",
                       {"email": email, "tenant_id": tenant_id, "role": role})


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[_ALG],
                          options={"require": ["exp"]})
    except Exception:
        raise HTTPException(401, "invalid or expired token")


bearer = OAuth2PasswordBearer(tokenUrl="/api/portal/auth/login", auto_error=False)


def current_employee(token: str = Depends(bearer),
                     db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(401, "not authenticated")
    data = _decode(token)
    if data.get("kind") != "employee":
        raise HTTPException(403, "employee token required")
    user = db.query(m.PortalUser).filter_by(id=data.get("sub")).first()
    if not user:
        raise HTTPException(401, "user not found")
    return user


def current_admin(token: str = Depends(bearer)) -> dict:
    if not token:
        raise HTTPException(401, "not authenticated")
    data = _decode(token)
    if data.get("kind") != "admin":
        raise HTTPException(403, "admin session required")
    return data
