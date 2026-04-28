"""Swap routers — face / scene / cloth swap."""
from __future__ import annotations

import os
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..workers import face_swap_task, scene_swap_task, cloth_swap_task

router = APIRouter(prefix="/swaps", tags=["swaps"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)

COSTS = {"face_swap": 8, "scene_swap": 10, "cloth_swap": 8}


class FaceSwap(BaseModel):
    source_image_url: str   # rosto que vai ser inserido
    target_image_url: str   # imagem onde substituir


class SceneSwap(BaseModel):
    persona_id: UUID
    scene_prompt: str       # ex: "Paris café terrace, golden hour"


class ClothSwap(BaseModel):
    person_image_url: str
    outfit_prompt: str


def _create_generation(user_id: str, kind: str, cost: int) -> str:
    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO generations (user_id, status, prompt, credits_used)
            VALUES (:u, 'queued', :k, :c) RETURNING id
        """), {"u": user_id, "k": kind, "c": cost}).first()
    return str(row.id)


@router.post("/face")
def face_swap(payload: FaceSwap, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["face_swap"]
    if user.credits < cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{cost})")
    gid = _create_generation(user.user_id, "face_swap", cost)
    deduct_credits(user.user_id, cost)
    face_swap_task.delay(generation_id=gid,
                         source_image=payload.source_image_url,
                         target_image=payload.target_image_url)
    return {"id": gid, "status": "queued", "credits_used": cost}


@router.post("/scene")
def scene_swap(payload: SceneSwap, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["scene_swap"]
    if user.credits < cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{cost})")

    with _engine.connect() as conn:
        p = conn.execute(text(
            "SELECT canonical_grid_url, reference_image_url FROM personas WHERE id=:id AND user_id=:u"
        ), {"id": str(payload.persona_id), "u": user.user_id}).first()
    if not p:
        raise HTTPException(404, "Persona não encontrada")
    persona_ref = p.canonical_grid_url or p.reference_image_url

    gid = _create_generation(user.user_id, "scene_swap", cost)
    deduct_credits(user.user_id, cost)
    scene_swap_task.delay(generation_id=gid, persona_ref=persona_ref, scene_prompt=payload.scene_prompt)
    return {"id": gid, "status": "queued", "credits_used": cost}


@router.post("/cloth")
def cloth_swap(payload: ClothSwap, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["cloth_swap"]
    if user.credits < cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{cost})")
    gid = _create_generation(user.user_id, "cloth_swap", cost)
    deduct_credits(user.user_id, cost)
    cloth_swap_task.delay(generation_id=gid,
                          person_image=payload.person_image_url,
                          outfit_prompt=payload.outfit_prompt)
    return {"id": gid, "status": "queued", "credits_used": cost}
