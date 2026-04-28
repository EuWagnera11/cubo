"""Personas + templates routers."""
from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser

router = APIRouter(prefix="/personas", tags=["personas"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


class PersonaCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    reference_image_url: Optional[str] = None
    canonical_grid_url: Optional[str] = None


class PersonaUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    reference_image_url: Optional[str] = None
    canonical_grid_url: Optional[str] = None


@router.post("")
def create_persona(payload: PersonaCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO personas (user_id, name, description, reference_image_url, canonical_grid_url)
            VALUES (:u, :n, :d, :ref, :grid) RETURNING id, name, created_at
        """), {
            "u": user.user_id, "n": payload.name, "d": payload.description,
            "ref": payload.reference_image_url, "grid": payload.canonical_grid_url,
        }).first()
    return dict(row._mapping)


@router.get("")
def list_personas(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM personas WHERE user_id=:u ORDER BY created_at DESC"
        ), {"u": user.user_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/{persona_id}")
def get_persona(persona_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM personas WHERE id=:id AND user_id=:u"
        ), {"id": persona_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


@router.patch("/{persona_id}")
def update_persona(persona_id: str, payload: PersonaUpdate, user: AuthUser = Depends(get_current_user)) -> dict:
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Nada pra atualizar")
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = persona_id
    fields["u"] = user.user_id
    with _engine.begin() as conn:
        r = conn.execute(text(
            f"UPDATE personas SET {sets}, updated_at=now() WHERE id=:id AND user_id=:u RETURNING *"
        ), fields).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


@router.delete("/{persona_id}")
def delete_persona(persona_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.begin() as conn:
        r = conn.execute(text(
            "DELETE FROM personas WHERE id=:id AND user_id=:u RETURNING id"
        ), {"id": persona_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return {"deleted": True}


# ─────────────── Templates ───────────────

templates_router = APIRouter(prefix="/templates", tags=["templates"])


@templates_router.get("")
def list_templates(category: Optional[str] = None, media_type: Optional[str] = None) -> list[dict]:
    q = "SELECT * FROM templates WHERE is_public=true"
    params: dict = {}
    if category:
        q += " AND category = :c"
        params["c"] = category
    if media_type:
        q += " AND media_type = :m"
        params["m"] = media_type
    q += " ORDER BY uses_count DESC LIMIT 100"
    with _engine.connect() as conn:
        rows = conn.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@templates_router.get("/{template_id}")
def get_template(template_id: str) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text("SELECT * FROM templates WHERE id=:id"), {"id": template_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


@templates_router.get("/categories/list")
def list_categories() -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT category, COUNT(*) as count FROM templates WHERE is_public=true GROUP BY category ORDER BY count DESC"
        )).fetchall()
    return [{"name": r.category, "count": r.count} for r in rows]
