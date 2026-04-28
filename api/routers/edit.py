"""Edit router — inpaint, outpaint, remove object, sketch-to-image, etc."""
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..freepik import get_freepik

router = APIRouter(prefix="/edit", tags=["edit"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


class InpaintReq(BaseModel):
    image_url: str
    mask_url: str
    prompt: str


class OutpaintReq(BaseModel):
    image_url: str
    prompt: str = ""
    direction: Literal["all", "horizontal", "vertical", "left", "right", "top", "bottom"] = "all"
    expansion_factor: float = Field(1.5, ge=1.1, le=3.0)


class RemoveObjectReq(BaseModel):
    image_url: str
    mask_url: str


class SketchToImageReq(BaseModel):
    sketch_url: str
    prompt: str
    strength: float = Field(0.7, ge=0.0, le=1.0)


class StyleTransferReq(BaseModel):
    source_url: str
    style_reference_url: str
    prompt: str = ""
    strength: float = Field(0.7, ge=0.0, le=1.0)


class ReplaceBackgroundReq(BaseModel):
    image_url: str
    prompt: str


class ExpandReq(BaseModel):
    image_url: str
    target_aspect_ratio: str = "16:9"


class ColorizeReq(BaseModel):
    image_url: str
    prompt: str = ""


COSTS = {
    "inpaint": 4, "outpaint": 4, "remove_object": 3,
    "sketch_to_image": 5, "style_transfer": 5,
    "replace_background": 4, "expand": 4, "colorize": 3,
}


def _create_edit_job(user_id: str, kind: str, source: str, **fields) -> str:
    cost = COSTS.get(kind, 5)
    fields["c"] = cost
    fields["u"] = user_id
    fields["k"] = kind
    fields["src"] = source
    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO edit_jobs (user_id, type, status, source_image_url, mask_url, prompt,
                                    reference_style_url, options, credits_used)
            VALUES (:u, :k, 'processing', :src, :mask, :p, :ref, :opts::jsonb, :c) RETURNING id
        """), {
            "u": user_id, "k": kind, "src": source,
            "mask": fields.get("mask"), "p": fields.get("prompt", ""),
            "ref": fields.get("ref"), "opts": fields.get("opts", "{}"),
            "c": cost,
        }).first()
    return str(row.id)


@router.post("/inpaint")
async def inpaint(payload: InpaintReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["inpaint"]
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.inpaint(payload.image_url, payload.mask_url, payload.prompt)
    eid = _create_edit_job(user.user_id, "inpaint", payload.image_url,
                           mask=payload.mask_url, prompt=payload.prompt)
    return {"id": eid, "task_id": task_id, "credits_used": cost}


@router.post("/outpaint")
async def outpaint(payload: OutpaintReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["outpaint"]
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.outpaint(payload.image_url, prompt=payload.prompt,
                                 direction=payload.direction,
                                 expansion_factor=payload.expansion_factor)
    eid = _create_edit_job(user.user_id, "outpaint", payload.image_url,
                           prompt=payload.prompt,
                           opts=f'{{"direction":"{payload.direction}","factor":{payload.expansion_factor}}}')
    return {"id": eid, "task_id": task_id, "credits_used": cost}


@router.post("/remove-object")
async def remove_object(payload: RemoveObjectReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["remove_object"]
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.remove_object(payload.image_url, payload.mask_url)
    eid = _create_edit_job(user.user_id, "remove_object", payload.image_url,
                           mask=payload.mask_url)
    return {"id": eid, "task_id": task_id, "credits_used": cost}


@router.post("/sketch-to-image")
async def sketch_to_image(payload: SketchToImageReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["sketch_to_image"]
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.sketch_to_image(payload.sketch_url, payload.prompt, strength=payload.strength)
    eid = _create_edit_job(user.user_id, "sketch_to_image", payload.sketch_url,
                           prompt=payload.prompt,
                           opts=f'{{"strength":{payload.strength}}}')
    return {"id": eid, "task_id": task_id, "credits_used": cost}


@router.post("/style-transfer")
async def style_transfer(payload: StyleTransferReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["style_transfer"]
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.style_transfer(payload.source_url, payload.style_reference_url,
                                       payload.prompt, strength=payload.strength)
    eid = _create_edit_job(user.user_id, "style_transfer", payload.source_url,
                           prompt=payload.prompt, ref=payload.style_reference_url,
                           opts=f'{{"strength":{payload.strength}}}')
    return {"id": eid, "task_id": task_id, "credits_used": cost}


@router.post("/replace-background")
async def replace_bg(payload: ReplaceBackgroundReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["replace_background"]
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.replace_background(payload.image_url, payload.prompt)
    eid = _create_edit_job(user.user_id, "replace_background", payload.image_url,
                           prompt=payload.prompt)
    return {"id": eid, "task_id": task_id, "credits_used": cost}


@router.post("/expand")
async def expand(payload: ExpandReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["expand"]
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.expand_image(payload.image_url, target_aspect_ratio=payload.target_aspect_ratio)
    eid = _create_edit_job(user.user_id, "expand", payload.image_url,
                           opts=f'{{"target_ar":"{payload.target_aspect_ratio}"}}')
    return {"id": eid, "task_id": task_id, "credits_used": cost}


@router.post("/colorize")
async def colorize(payload: ColorizeReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = COSTS["colorize"]
    if user.credits < cost: raise HTTPException(402)
    deduct_credits(user.user_id, cost)
    fp = get_freepik()
    task_id = await fp.colorize(payload.image_url, payload.prompt)
    eid = _create_edit_job(user.user_id, "colorize", payload.image_url,
                           prompt=payload.prompt)
    return {"id": eid, "task_id": task_id, "credits_used": cost}


@router.get("/{job_id}")
def get_edit_job(job_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM edit_jobs WHERE id=:id AND user_id=:u"
        ), {"id": job_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


@router.get("")
def list_edits(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM edit_jobs WHERE user_id=:u ORDER BY created_at DESC LIMIT 50"
        ), {"u": user.user_id}).fetchall()
    return [dict(r._mapping) for r in rows]
