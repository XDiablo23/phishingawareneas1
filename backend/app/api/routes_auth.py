"""
Auth routes: login, logout.

Login both returns the JWT in the JSON body (for API/script clients, per
the documented curl examples in docs/GoPhish_Integration.md) and sets it as
an httpOnly session cookie (for the browser console) - see
app/api/security.py's module docstring for why both exist side by side.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db import models as m
from app.api.security import (
    verify_password, create_access_token, set_auth_cookies, clear_auth_cookies,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
def login(response: Response, form: OAuth2PasswordRequestForm = Depends(),
          db: Session = Depends(get_db)):
    """OAuth2 password flow. `username` is the user's email."""
    user = db.query(m.User).filter_by(email=form.username).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, "incorrect email or password")
    token = create_access_token(user)
    set_auth_cookies(response, token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role.value if hasattr(user.role, "value") else user.role,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "department_scope": user.department_scope,
    }


@router.post("/logout")
def logout(response: Response):
    """Clears the session + CSRF cookies. Idempotent and unauthenticated by
    design (there is no server-side session to invalidate - JWTs are
    stateless - so this is just cookie cleanup; it works even if the cookie
    already expired or was never set)."""
    clear_auth_cookies(response)
    return {"status": "logged_out"}
