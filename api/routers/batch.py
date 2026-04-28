"""Batch router — mass image/video generation."""
from __future__ import annotations

import os
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..workers import batch_image_task, batch_video_task

router = APIRouter(prefix="/batch", tags=["batch"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


class BatchImageCreate(BaseModel):
    persona_id: UUID
    template_ids: list[UUID] = Field(..., min_length=1, max_length=20)
    num_per_template: int = Field(4, ge=1, le=8)


class BatchVideoCreate(BaseModel):
    image_urls: list[str] = Field(..., min_length=1, max_length=20)
    prompt: str
    engine: Literal["kling_v3", "kling_v2_1", "hailuo"] = "kling_v3"


@router.post("/images")
def batch_images(payload: BatchImageCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    total_jobs = len(payload.template_ids) * payload.num_per_template
    cost_per = 8  # 2K + 1 var + skin enhance
    total_cost = total_jobs * cost_per

    if user.credits < total_cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{total_cost})")

    with _engine.connect() as conn:
        p = conn.execute(text(
            "SELECT canonical_grid_url, reference_image_url FROM personas WHERE id=:id AND user_id=:u"
        ), {"id": str(payload.persona_id), "u": user.user_id}).first()
    if not p:
        raise HTTPException(404, "Persona não encontrada")
    persona_ref = p.canonical_grid_url or p.reference_image_url

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO batch_jobs (user_id, type, persona_id, config, status, total_credits_used)
            VALUES (:u, 'batch_image', :pid, :cfg::jsonb, 'queued', :c) RETURNING id
        """), {
            "u": user.user_id, "pid": str(payload.persona_id), "c": total_cost,
            "cfg": f'{{"template_ids": {[str(t) for t in payload.template_ids]}, "num_per_template": {payload.num_per_template}}}'.replace("'", '"'),
        }).first()
        bid = str(row.id)

    deduct_credits(user.user_id, total_cost)
    batch_image_task.delay(
        batch_id=bid,
        persona_id=str(payload.persona_id),
        persona_ref=persona_ref,
        template_ids=[str(t) for t in payload.template_ids],
        num_per_template=payload.num_per_template,
    )
    return {"id": bid, "total_jobs": total_jobs, "credits_used": total_cost}


@router.post("/videos")
def batch_videos(payload: BatchVideoCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    cost_per = 25 if payload.engine == "kling_v3" else 20
    total_cost = len(payload.image_urls) * cost_per

    if user.credits < total_cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{total_cost})")

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO batch_jobs (user_id, type, config, status, total_credits_used)
            VALUES (:u, 'batch_video', :cfg::jsonb, 'queued', :c) RETURNING id
        """), {
            "u": user.user_id, "c": total_cost,
            "cfg": f'{{"engine": "{payload.engine}", "prompt": "{payload.prompt[:200]}"}}',
        }).first()
        bid = str(row.id)

    deduct_credits(user.user_id, total_cost)
    batch_video_task.delay(
        batch_id=bid, image_urls=payload.image_urls,
        prompt=payload.prompt, engine=payload.engine,
    )
    return {"id": bid, "total_jobs": len(payload.image_urls), "credits_used": total_cost}


@router.get("/{batch_id}")
def get_batch(batch_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM batch_jobs WHERE id=:id AND user_id=:u"
        ), {"id": batch_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


@router.get("")
def list_batches(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM batch_jobs WHERE user_id=:u ORDER BY created_at DESC LIMIT 50"
        ), {"u": user.user_id}).fetchall()
    return [dict(r._mapping) for r in rows]
