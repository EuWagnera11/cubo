"""Generations router — image + video generation."""
from __future__ import annotations

from typing import Optional, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
import os

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..workers import generate_image_task, generate_video_task

router = APIRouter(prefix="/generations", tags=["generations"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


class GenerationCreate(BaseModel):
    persona_id: Optional[UUID] = None
    template_id: Optional[UUID] = None
    learned_style_id: Optional[UUID] = None
    prompt: Optional[str] = None
    aspect_ratio: str = "4:5"
    resolution: Literal["1k", "2k", "4k"] = "2k"
    num_variations: int = Field(4, ge=1, le=8)
    media_type: Literal["image", "video"] = "image"
    enhance_skin: bool = True
    upscale: bool = False

    # Modelo escolhido pelo usuário (default = Nano Banana Pro Flash 2K, melhor custo-benefício)
    model: str = "nano-banana-pro-flash"

    # video-specific
    image_url: Optional[str] = None
    video_engine: str = "kling-v3-std"
    duration: str = "5s"
    with_audio: bool = False


def _aspect_to_freepik(ratio: str) -> str:
    """API atual da Magnific/Freepik aceita formato simples ('1:1', '16:9').
    Mantém função pra retro-compat — só passa o ratio adiante."""
    if ratio.startswith("square_") or ratio.startswith("portrait_") or ratio.startswith("social_") or ratio.startswith("widescreen_"):
        # Já está no formato antigo; converte de volta pra simples
        legacy = {
            "square_1_1": "1:1", "portrait_4_5": "4:5", "portrait_3_4": "3:4",
            "social_story_9_16": "9:16", "widescreen_16_9": "16:9",
        }
        return legacy.get(ratio, "1:1")
    return ratio if ratio else "1:1"


def _cost(payload: GenerationCreate) -> int:
    """
    Calcula custo em créditos via lookup table central (api/pricing.py).
    Pesos seguem multiplicador ×1.785 sobre custo USD Freepik (NB2 1K = 75 cred).
    """
    from ..pricing import get_image_cost, get_video_cost, ENHANCE_COSTS

    if payload.media_type == "video":
        cost = get_video_cost(
            payload.video_engine,
            duration=payload.duration,
            audio=payload.with_audio,
        )
        if cost is None:
            raise HTTPException(
                400,
                f"Combinação não suportada: {payload.video_engine} / "
                f"{payload.duration} / audio={payload.with_audio}",
            )
        return cost

    # Imagem
    per_image = get_image_cost(payload.model, payload.resolution)
    if per_image is None:
        raise HTTPException(
            400,
            f"Modelo '{payload.model}' não suporta resolução '{payload.resolution}'.",
        )

    cost = per_image * payload.num_variations

    # Upscale opcional (Magnific 2K→4K)
    if payload.upscale:
        upscale_key = f"magnific_{payload.resolution}_to_4k" if payload.resolution != "4k" else None
        if upscale_key and upscale_key in ENHANCE_COSTS:
            cost += ENHANCE_COSTS[upscale_key] * payload.num_variations

    # Skin enhance opcional (Creative — default mais barato)
    if payload.enhance_skin:
        cost += ENHANCE_COSTS["skin_creative"] * payload.num_variations

    return cost


@router.post("")
async def create_generation(payload: GenerationCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = _cost(payload)
    if user.credits < cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{cost})")

    # Resolve prompt: template or learned_style or raw
    prompt = payload.prompt or ""
    persona_ref = None
    with _engine.connect() as conn:
        if payload.persona_id:
            r = conn.execute(text("SELECT canonical_grid_url, reference_image_url FROM personas WHERE id=:id AND user_id=:u"),
                             {"id": str(payload.persona_id), "u": user.user_id}).first()
            if not r:
                raise HTTPException(404, "Persona não encontrada")
            persona_ref = r.canonical_grid_url or r.reference_image_url
        if payload.template_id:
            t = conn.execute(text("SELECT prompt FROM templates WHERE id=:id"),
                             {"id": str(payload.template_id)}).first()
            if t:
                prompt = f"{t.prompt}. {prompt}".strip(". ").strip()
        if payload.learned_style_id:
            s = conn.execute(text("SELECT prompt_template FROM learned_styles WHERE id=:id AND user_id=:u"),
                             {"id": str(payload.learned_style_id), "u": user.user_id}).first()
            if s:
                prompt = f"{s.prompt_template}. {prompt}".strip(". ").strip()

    # Insert generation row (registra source_image_path pra debug — se for video)
    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO generations
              (user_id, persona_id, template_id, learned_style_id, status,
               prompt, aspect_ratio, resolution, num_variations, credits_used, media_type,
               source_image_path)
            VALUES
              (:u, :pid, :tid, :sid, 'queued', :p, :ar, :res, :n, :c, :m, :sip)
            RETURNING id
        """), {
            "u": user.user_id, "pid": str(payload.persona_id) if payload.persona_id else None,
            "tid": str(payload.template_id) if payload.template_id else None,
            "sid": str(payload.learned_style_id) if payload.learned_style_id else None,
            "p": prompt, "ar": payload.aspect_ratio, "res": payload.resolution,
            "n": payload.num_variations, "c": cost, "m": payload.media_type,
            "sip": payload.image_url if payload.media_type == "video" else None,
        }).first()
        gid = str(row.id)

    deduct_credits(user.user_id, cost)

    # Dispatch worker
    if payload.media_type == "video":
        if not payload.image_url:
            raise HTTPException(400, "image_url obrigatório pra vídeo")
        generate_video_task.delay(
            generation_id=gid, image_url=payload.image_url, prompt=prompt,
            engine=payload.video_engine, duration=payload.duration,
        )
    else:
        generate_image_task.delay(
            generation_id=gid, prompt=prompt, persona_ref_url=persona_ref,
            user_image_url=payload.image_url,  # imagem que user anexou no front
            aspect_ratio=_aspect_to_freepik(payload.aspect_ratio),
            resolution=payload.resolution, num_variations=payload.num_variations,
            enhance_skin=payload.enhance_skin, upscale=payload.upscale,
            model=payload.model,
        )

    return {"id": gid, "status": "queued", "credits_used": cost}


@router.get("/{generation_id}")
def get_generation(generation_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM generations WHERE id=:id AND user_id=:u"
        ), {"id": generation_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


@router.get("")
def list_generations(limit: int = 50, offset: int = 0, user: AuthUser = Depends(get_current_user)) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, status, prompt, image_urls, video_urls, media_type, credits_used,
                   created_at, completed_at
            FROM generations WHERE user_id=:u
            ORDER BY created_at DESC LIMIT :l OFFSET :o
        """), {"u": user.user_id, "l": limit, "o": offset}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.delete("/{generation_id}")
def delete_generation(generation_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.begin() as conn:
        result = conn.execute(text(
            "DELETE FROM generations WHERE id=:id AND user_id=:u RETURNING id"
        ), {"id": generation_id, "u": user.user_id}).first()
    if not result:
        raise HTTPException(404)
    return {"deleted": True}
