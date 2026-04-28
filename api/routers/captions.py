"""Captions / hashtags / story generator router (Claude Opus 4.7)."""
from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from .. import captions as cap

router = APIRouter(prefix="/captions", tags=["captions"])


class CaptionReq(BaseModel):
    image_url: str
    tone: Literal["casual", "professional", "playful", "inspirational", "minimalist", "storytelling"] = "casual"
    language: str = "pt-BR"
    max_length: int = Field(280, ge=50, le=2200)


class HashtagReq(BaseModel):
    image_url: str
    count: int = Field(20, ge=5, le=30)
    language: str = "pt-BR"


class StoryReq(BaseModel):
    theme: str
    n_posts: int = Field(7, ge=3, le=15)
    language: str = "pt-BR"


class CarouselReq(BaseModel):
    brief: str
    n_posts: int = Field(10, ge=3, le=15)


class BrandVoiceReq(BaseModel):
    text_samples: list[str] = Field(..., min_length=3, max_length=20)


@router.post("/caption")
async def caption(payload: CaptionReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 2
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    text = await cap.generate_caption(payload.image_url, tone=payload.tone,
                                        language=payload.language, max_length=payload.max_length)
    return {"caption": text, "credits_used": cost}


@router.post("/hashtags")
async def hashtags(payload: HashtagReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 1
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    tags = await cap.generate_hashtags(payload.image_url, count=payload.count, language=payload.language)
    return {"hashtags": tags, "credits_used": cost}


@router.post("/story")
async def story(payload: StoryReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 5
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    posts = await cap.generate_story(payload.theme, n_posts=payload.n_posts, language=payload.language)
    return {"posts": posts, "credits_used": cost}


@router.post("/carousel")
async def carousel(payload: CarouselReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 3
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    prompts = await cap.generate_carousel_prompts(payload.brief, n_posts=payload.n_posts)
    return {"prompts": prompts, "credits_used": cost}


@router.post("/brand-voice")
async def brand_voice(payload: BrandVoiceReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 5
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    analysis = await cap.analyze_brand_voice(payload.text_samples)
    return {"analysis": analysis, "credits_used": cost}
