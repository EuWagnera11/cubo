"""Catalog routers — worlds (cenários) + model presets."""
from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser

worlds_router = APIRouter(prefix="/worlds", tags=["worlds"])
presets_router = APIRouter(prefix="/presets", tags=["presets"])
voices_router = APIRouter(prefix="/voices-public", tags=["voices"])
music_router = APIRouter(prefix="/music-library", tags=["music"])

_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


# ─────────────── WORLDS ───────────────

class WorldCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    prompt_template: str
    reference_images: list[str] = []
    is_public: bool = False


@worlds_router.get("")
def list_worlds(category: Optional[str] = None, user: AuthUser = Depends(get_current_user)) -> list[dict]:
    q = "SELECT * FROM worlds WHERE (user_id IS NULL OR user_id = :u OR is_public = true)"
    params: dict = {"u": user.user_id}
    if category:
        q += " AND category = :c"
        params["c"] = category
    q += " ORDER BY uses_count DESC, created_at DESC LIMIT 200"
    with _engine.connect() as conn:
        rows = conn.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@worlds_router.post("")
def create_world(payload: WorldCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO worlds (user_id, name, description, category, prompt_template, reference_images, is_public)
            VALUES (:u, :n, :d, :cat, :p, :refs, :pub) RETURNING *
        """), {
            "u": user.user_id, "n": payload.name, "d": payload.description,
            "cat": payload.category, "p": payload.prompt_template,
            "refs": "{" + ",".join(payload.reference_images) + "}",
            "pub": payload.is_public,
        }).first()
    return dict(row._mapping)


@worlds_router.delete("/{world_id}")
def delete_world(world_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.begin() as conn:
        r = conn.execute(text(
            "DELETE FROM worlds WHERE id=:id AND user_id=:u RETURNING id"
        ), {"id": world_id, "u": user.user_id}).first()
    if not r: raise HTTPException(404)
    return {"deleted": True}


@worlds_router.get("/categories")
def world_categories() -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT category, COUNT(*) as count FROM worlds WHERE is_public=true GROUP BY category ORDER BY count DESC"
        )).fetchall()
    return [{"name": r.category, "count": r.count} for r in rows]


# ─────────────── MODEL PRESETS ───────────────

@presets_router.get("")
def list_presets(category: Optional[str] = None, gender: Optional[str] = None) -> list[dict]:
    q = "SELECT * FROM model_presets WHERE 1=1"
    params: dict = {}
    if category:
        q += " AND category = :c"; params["c"] = category
    if gender:
        q += " AND gender = :g"; params["g"] = gender
    q += " ORDER BY uses_count DESC, rating DESC LIMIT 100"
    with _engine.connect() as conn:
        rows = conn.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@presets_router.get("/categories")
def preset_categories() -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT category, COUNT(*) as count FROM model_presets GROUP BY category ORDER BY count DESC"
        )).fetchall()
    return [{"name": r.category, "count": r.count} for r in rows]


@presets_router.post("/{preset_id}/use")
def use_preset(preset_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    """Cria uma persona a partir de um preset."""
    with _engine.connect() as conn:
        p = conn.execute(text("SELECT * FROM model_presets WHERE id=:id"), {"id": preset_id}).first()
    if not p: raise HTTPException(404)

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO personas (user_id, name, description, reference_image_url, canonical_grid_url, attributes)
            VALUES (:u, :n, :d, :ref, :grid, :attr::jsonb) RETURNING id, name
        """), {
            "u": user.user_id, "n": p.name, "d": p.description,
            "ref": p.reference_image_url, "grid": p.canonical_grid_url,
            "attr": '{"from_preset": "' + preset_id + '"}',
        }).first()
        conn.execute(text("UPDATE model_presets SET uses_count = uses_count + 1 WHERE id=:id"),
                     {"id": preset_id})
    return {"persona_id": str(row.id), "name": row.name, "preset_id": preset_id}


# ─────────────── MUSIC LIBRARY ───────────────

@music_router.get("")
def list_music(genre: Optional[str] = None, mood: Optional[str] = None,
                user: AuthUser = Depends(get_current_user)) -> list[dict]:
    q = "SELECT * FROM music_tracks WHERE (user_id IS NULL OR user_id = :u OR is_public = true)"
    params: dict = {"u": user.user_id}
    if genre: q += " AND genre = :g"; params["g"] = genre
    if mood:  q += " AND mood = :m"; params["m"] = mood
    q += " ORDER BY uses_count DESC LIMIT 100"
    with _engine.connect() as conn:
        rows = conn.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]
