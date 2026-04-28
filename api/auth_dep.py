"""
Refine — auth dependency (validates Supabase JWT).
"""
from __future__ import annotations

import os
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from sqlalchemy import create_engine, text

SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/refine")

bearer = HTTPBearer(auto_error=False)
_engine = create_engine(DATABASE_URL.replace("+asyncpg", ""), pool_pre_ping=True)


class AuthUser:
    def __init__(self, user_id: str, email: str = "", tier: str = "free", credits: int = 0, role: str = "creator"):
        self.user_id = user_id
        self.email = email
        self.tier = tier
        self.credits = credits
        self.role = role


def get_current_user(token: HTTPAuthorizationCredentials = Depends(bearer)) -> AuthUser:
    """Valida JWT do Supabase + carrega profile do user."""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    secret = SUPABASE_JWT_SECRET or JWT_SECRET
    try:
        payload = jwt.decode(token.credentials, secret, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")

    user_id = payload.get("sub")
    email = payload.get("email", "")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing sub claim")

    # Load profile
    with _engine.connect() as conn:
        row = conn.execute(text(
            "SELECT tier, credits FROM profiles WHERE id = :id"
        ), {"id": user_id}).first()

    return AuthUser(
        user_id=user_id, email=email,
        tier=row.tier if row else "free",
        credits=row.credits if row else 0,
    )


def require_credits(min_credits: int):
    """Dependency factory que valida saldo de créditos."""
    def _dep(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.credits < min_credits:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED,
                                f"Créditos insuficientes ({user.credits}/{min_credits})")
        return user
    return _dep


def deduct_credits(user_id: str, amount: int):
    """Decrementa créditos do user (chamado dentro de transaction)."""
    with _engine.begin() as conn:
        conn.execute(text(
            "UPDATE profiles SET credits = credits - :n WHERE id = :id AND credits >= :n"
        ), {"n": amount, "id": user_id})
