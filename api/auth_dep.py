"""
Refine — auth dependency (validates Supabase JWT).

Suporta DOIS modos de assinatura JWT do Supabase:
  - Modern (asymmetric ES256/RS256): valida via JWKS endpoint
  - Legacy (symmetric HS256): valida com SUPABASE_JWT_SECRET

Tenta primeiro JWKS (modern), faz fallback pra HS256 se a chave nao bater.
Anonymous sign-in do Supabase (sb_publishable_*) usa ES256 sempre.
"""
from __future__ import annotations

import os
from typing import Optional

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from sqlalchemy import create_engine, text

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/refine")

bearer = HTTPBearer(auto_error=False)
_engine = create_engine(DATABASE_URL.replace("+asyncpg", ""), pool_pre_ping=True)

# JWKS client (cache de chaves publicas; refresh automatico em key rotation)
_jwks_client: Optional[PyJWKClient] = None
if SUPABASE_URL:
    _jwks_url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        _jwks_client = PyJWKClient(_jwks_url, cache_keys=True, lifespan=3600)
    except Exception as e:
        print(f"[auth] PyJWKClient init failed: {e}")


class AuthUser:
    def __init__(self, user_id: str, email: str = "", tier: str = "free", credits: int = 0, role: str = "creator"):
        self.user_id = user_id
        self.email = email
        self.tier = tier
        self.credits = credits
        self.role = role


def _decode_jwt(raw_token: str) -> dict:
    """Decodifica JWT tentando JWKS (ES256/RS256) primeiro, HS256 como fallback."""
    last_err: Exception = jwt.PyJWTError("no decoder available")

    # 1. Tentativa JWKS (Supabase modern + anonymous + OAuth)
    if _jwks_client is not None:
        try:
            unverified = jwt.get_unverified_header(raw_token)
            alg = unverified.get("alg", "")
            if alg in ("ES256", "RS256", "ES384", "RS384", "ES512", "RS512"):
                signing_key = _jwks_client.get_signing_key_from_jwt(raw_token).key
                return jwt.decode(
                    raw_token, signing_key,
                    algorithms=[alg], audience="authenticated",
                    options={"verify_iss": False},
                )
        except jwt.PyJWTError as e:
            last_err = e
        except Exception as e:
            last_err = e  # network etc

    # 2. Fallback HS256 (legacy SUPABASE_JWT_SECRET)
    secret = SUPABASE_JWT_SECRET or JWT_SECRET
    if secret:
        try:
            return jwt.decode(
                raw_token, secret,
                algorithms=["HS256"], audience="authenticated",
                options={"verify_iss": False},
            )
        except jwt.PyJWTError as e:
            last_err = e

    raise last_err


def get_current_user(token: HTTPAuthorizationCredentials = Depends(bearer)) -> AuthUser:
    """Valida JWT do Supabase + carrega profile do user (cria se não existir)."""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    try:
        payload = _decode_jwt(token.credentials)
    except Exception as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")

    user_id = payload.get("sub")
    email = payload.get("email", "")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing sub claim")

    # Load profile (bootstrap se não existir — Postgres local não tem trigger handle_new_user)
    with _engine.begin() as conn:
        row = conn.execute(text(
            "SELECT tier, credits FROM profiles WHERE id = :id"
        ), {"id": user_id}).first()

        if not row:
            # Cria profile no first-touch
            conn.execute(text("""
                INSERT INTO profiles (id, email, tier, credits)
                VALUES (:id, :email, 'free', 0)
                ON CONFLICT (id) DO NOTHING
            """), {"id": user_id, "email": email})
            tier_val, credits_val = "free", 0
        else:
            tier_val, credits_val = row.tier, row.credits

    return AuthUser(
        user_id=user_id, email=email,
        tier=tier_val, credits=credits_val,
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


# ════════════════════════════════════════════════════════════════
#                          DAILY CAPS
# ════════════════════════════════════════════════════════════════
# Limites diários por modelo+plano pra evitar abuso de margem.
# Tabela definida em api/pricing.py:DAILY_CAPS.

def check_daily_cap(user_id: str, tier: str, model: str) -> None:
    """
    Verifica se usuário ainda pode usar `model` hoje.
    Levanta 429 se cap atingido.
    Cap=0 → bloqueia totalmente. Cap=None → sem limite.
    """
    # Import lazy pra evitar circular
    from .pricing import get_daily_cap

    cap = get_daily_cap(tier, model)
    if cap is None:
        return  # ilimitado neste plano

    if cap == 0:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Modelo '{model}' não disponível no plano {tier}. "
            f"Faça upgrade ou compre add-on.",
        )

    # Conta usos do user nesse modelo nas últimas 24h
    with _engine.connect() as conn:
        row = conn.execute(text("""
            SELECT COUNT(*) AS n FROM daily_usage
             WHERE user_id = :u AND model = :m
               AND used_at > NOW() - INTERVAL '24 hours'
        """), {"u": user_id, "m": model}).first()
    used_today = row.n if row else 0

    if used_today >= cap:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Limite diário atingido neste modelo ({used_today}/{cap}). "
            f"Volta amanhã ou compre Boost.",
        )


def record_usage(user_id: str, model: str) -> None:
    """Registra uso do modelo pra contagem de cap diário."""
    with _engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO daily_usage (user_id, model, used_at)
            VALUES (:u, :m, NOW())
        """), {"u": user_id, "m": model})
