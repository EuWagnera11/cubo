"""Specialized router — multi-view, headshot, ecommerce, magazine, etc."""
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from .. import specialized as spec

router = APIRouter(prefix="/specialized", tags=["specialized"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


# ─────────────── Models ───────────────

class MultiViewReq(BaseModel):
    persona_ref: str
    num_angles: int = 4


class HairChangeReq(BaseModel):
    image_url: str
    color: str = ""
    style: str = ""


class ExpressionReq(BaseModel):
    image_url: str
    expression: str


class AgeChangeReq(BaseModel):
    image_url: str
    target_age: int


class TwinReq(BaseModel):
    persona_ref: str
    scene_prompt: str


class HeadshotReq(BaseModel):
    persona_ref: str
    style: Literal["corporate", "creative", "casual", "editorial"] = "corporate"


class EcommerceReq(BaseModel):
    product_image_url: str
    mode: Literal["white_bg", "lifestyle", "luxury"] = "white_bg"
    scene_prompt: str = ""


class RealEstateReq(BaseModel):
    property_image_url: str
    style: str = "modern"


class FoodReq(BaseModel):
    food_image_url: str
    mood: str = "bright airy"


class MagazineCoverReq(BaseModel):
    persona_ref: str
    magazine_name: str = "VOGUE"
    theme: str = "editorial fashion"
    headline: str = ""


class YouTubeThumbReq(BaseModel):
    persona_ref: str
    theme: str
    big_text: str = ""


class PassportReq(BaseModel):
    persona_ref: str


class MaternityReq(BaseModel):
    persona_ref: str
    weeks: int = 32


class WeddingReq(BaseModel):
    persona_ref: str
    scene: str = "garden"


class FamilyReq(BaseModel):
    persona_refs: list[str]
    scene: str = "park sunset"


class PhotoRestoreReq(BaseModel):
    image_url: str
    colorize: bool = True
    upscale: bool = True


# ─────────────── Helper ───────────────

def _create_generation(user_id: str, kind: str, cost: int) -> str:
    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO generations (user_id, status, prompt, credits_used)
            VALUES (:u, 'processing', :p, :c) RETURNING id
        """), {"u": user_id, "p": kind, "c": cost}).first()
    return str(row.id)


def _save_result(generation_id: str, urls: list[str]):
    with _engine.begin() as conn:
        conn.execute(text("""
            UPDATE generations SET status='completed', image_urls=:u, completed_at=now() WHERE id=:id
        """), {"u": "{" + ",".join(urls) + "}", "id": generation_id})


# ─────────────── Endpoints ───────────────

@router.post("/multi-view")
async def multi_view(payload: MultiViewReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 6 * payload.num_angles
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    gid = _create_generation(user.user_id, "multi_view", cost)
    urls = await spec.multi_view(payload.persona_ref, num_angles=payload.num_angles)
    _save_result(gid, urls)
    return {"id": gid, "urls": urls, "credits_used": cost}


@router.post("/hair-change")
async def hair_change(payload: HairChangeReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 5
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.hair_change(payload.image_url, color=payload.color, style=payload.style)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/expression-change")
async def expression_change(payload: ExpressionReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 4
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.expression_change(payload.image_url, payload.expression)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/age-change")
async def age_change(payload: AgeChangeReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 5
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.age_change(payload.image_url, target_age=payload.target_age)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/twin")
async def twin(payload: TwinReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 8
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.twin_generation(payload.persona_ref, payload.scene_prompt)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/headshot-pro")
async def headshot_pro(payload: HeadshotReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 6
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.headshot_pro(payload.persona_ref, style=payload.style)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/ecommerce")
async def ecommerce(payload: EcommerceReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 5
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.ecommerce_product(payload.product_image_url, mode=payload.mode,
                                             scene_prompt=payload.scene_prompt)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/real-estate")
async def real_estate(payload: RealEstateReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 6
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.real_estate_enhance(payload.property_image_url, style=payload.style)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/food")
async def food(payload: FoodReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 5
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.food_photography(payload.food_image_url, mood=payload.mood)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/magazine-cover")
async def magazine(payload: MagazineCoverReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 12
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.magazine_cover(payload.persona_ref, magazine_name=payload.magazine_name,
                                          theme=payload.theme, headline=payload.headline)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/youtube-thumbnail")
async def youtube_thumb(payload: YouTubeThumbReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 8
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.youtube_thumbnail(payload.persona_ref, theme=payload.theme,
                                             big_text=payload.big_text)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/passport")
async def passport(payload: PassportReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 4
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.passport_photo(payload.persona_ref)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/maternity")
async def maternity(payload: MaternityReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 8
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.maternity_session(payload.persona_ref, weeks=payload.weeks)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/wedding")
async def wedding(payload: WeddingReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 10
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.wedding_session(payload.persona_ref, scene=payload.scene)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/family-portrait")
async def family(payload: FamilyReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 12
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    task_id = await spec.family_portrait(payload.persona_refs, scene=payload.scene)
    return {"task_id": task_id, "credits_used": cost}


@router.post("/photo-restoration")
async def photo_restoration(payload: PhotoRestoreReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 15  # 3 stages
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    result = await spec.photo_restoration(payload.image_url, colorize=payload.colorize,
                                            upscale=payload.upscale)
    gid = _create_generation(user.user_id, "photo_restoration", cost)
    _save_result(gid, [result["final"]])
    return {"id": gid, "credits_used": cost, **result}
