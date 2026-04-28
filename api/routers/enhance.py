"""Enhancers — upscale, skin enhance, background remove, relight."""
from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..freepik import get_freepik

router = APIRouter(prefix="/enhance", tags=["enhance"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


class UpscaleReq(BaseModel):
    image_url: str
    scale: Literal[2, 4] = 2
    engine: Literal["magnific_sparkle", "magnific_illusio", "magnific_sharpy"] = "magnific_sparkle"
    creativity: int = 0
    hdr: int = 0
    resemblance: int = 50


class SkinEnhanceReq(BaseModel):
    image_url: str
    mode: Literal["faithful", "flexible"] = "faithful"
    skin_detail: int = 20
    smart_grain: int = 0


class BackgroundRemoveReq(BaseModel):
    image_url: str


class RelightReq(BaseModel):
    image_url: str
    prompt: str


@router.post("/upscale")
async def upscale(payload: UpscaleReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 5 if payload.scale == 2 else 10
    if user.credits < cost:
        raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.magnific_upscaler(
        payload.image_url, scale=payload.scale, engine=payload.engine,
        creativity=payload.creativity, hdr=payload.hdr, resemblance=payload.resemblance,
    )
    return {"task_id": task_id, "credits_used": cost}


@router.post("/skin")
async def skin_enhance(payload: SkinEnhanceReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 3
    if user.credits < cost:
        raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.skin_enhancer(
        payload.image_url, mode=payload.mode,
        skin_detail=payload.skin_detail, smart_grain=payload.smart_grain,
    )
    return {"task_id": task_id, "credits_used": cost}


@router.post("/background-remove")
async def background_remove(payload: BackgroundRemoveReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 2
    if user.credits < cost:
        raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.background_remover(payload.image_url)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/relight")
async def relight(payload: RelightReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 4
    if user.credits < cost:
        raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.relight(payload.image_url, payload.prompt)
    return {"task_id": task_id, "credits_used": cost}


@router.get("/task/{task_id}")
async def get_task_status(task_id: str, kind: Literal["image", "video", "enhance"] = "enhance",
                          user: AuthUser = Depends(get_current_user)) -> dict:
    fp = get_freepik()
    return await fp.get_task(task_id, kind=kind)
