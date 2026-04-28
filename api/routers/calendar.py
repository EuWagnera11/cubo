"""Content Calendar router — gerar mês inteiro a partir de brief/pack."""
from __future__ import annotations

import os
import json
from datetime import date, timedelta
from typing import Optional, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..workers import calendar_generate_task

router = APIRouter(prefix="/calendar", tags=["calendar"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


# ─────────────── Models ───────────────

class CalendarCreate(BaseModel):
    persona_id: UUID
    name: str = Field(..., min_length=2, max_length=200)
    brief: Optional[str] = Field(None, max_length=2000,
                                   description="Contexto/tema do mês (ex: 'Lançamento de coleção verão tropical')")
    pack_key: Optional[str] = Field(None, description="lifestyle_30d, travel_30d, fashion_30d, fitness_30d, professional_30d, beach_summer_15d, content_creator_7d")
    custom_prompts: Optional[list[str]] = Field(None,
                                                  description="Lista de prompts customizados (1 por post). Se preenchido, ignora pack")
    n_posts: int = Field(30, ge=1, le=60)
    start_date: Optional[date] = None
    enhance_skin: bool = True
    upscale: bool = False


# ─────────────── Endpoints ───────────────

@router.get("/packs")
def list_packs() -> list[dict]:
    """Lista todos packs pré-curados disponíveis."""
    with _engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT key, name, description, category, duration_days, recommended_credits, is_premium
            FROM content_packs
            ORDER BY category, duration_days
        """)).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/packs/{pack_key}")
def get_pack(pack_key: str) -> dict:
    """Detalhes de um pack — incluindo template_pattern."""
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM content_packs WHERE key = :k"
        ), {"k": pack_key}).first()
    if not r:
        raise HTTPException(404, f"Pack '{pack_key}' não encontrado")
    return dict(r._mapping)


@router.post("")
def create_calendar(payload: CalendarCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    """
    Cria calendário e dispara batch de geração.

    Estratégia:
      1. Se custom_prompts: usa direto (1 prompt → 1 post)
      2. Senão: usa pack_key pra puxar template_pattern do DB
      3. Pra cada day do pattern: busca template pelo nome, monta prompt
      4. Cria N generations + dispara worker

    Custo: ~8 créditos/post (2K + skin enhance) × n_posts.
      - 30 posts = ~240 créditos (R$ 14 no plano Creator)
      - 7 posts  = ~56 créditos
    """
    # Validar persona
    with _engine.connect() as conn:
        per = conn.execute(text(
            "SELECT canonical_grid_url, reference_image_url FROM personas WHERE id=:id AND user_id=:u"
        ), {"id": str(payload.persona_id), "u": user.user_id}).first()
    if not per:
        raise HTTPException(404, "Persona não encontrada")
    persona_ref = per.canonical_grid_url or per.reference_image_url

    # Resolver lista de prompts
    prompts: list[dict] = []  # [{date_str, prompt, template_id, category}]
    start = payload.start_date or date.today()

    if payload.custom_prompts:
        # Modo manual
        for i, p in enumerate(payload.custom_prompts[:payload.n_posts]):
            prompts.append({
                "date": (start + timedelta(days=i)).isoformat(),
                "prompt": p, "template_id": None, "category": "custom",
            })
    elif payload.pack_key:
        # Modo pack
        with _engine.connect() as conn:
            pack = conn.execute(text(
                "SELECT template_pattern, name FROM content_packs WHERE key = :k"
            ), {"k": payload.pack_key}).first()
        if not pack:
            raise HTTPException(404, f"Pack '{payload.pack_key}' não encontrado")

        pattern = pack.template_pattern if isinstance(pack.template_pattern, list) else json.loads(pack.template_pattern)
        for entry in pattern[:payload.n_posts]:
            day = entry.get("day", len(prompts) + 1)
            sub = entry.get("sub", "")
            cat = entry.get("category", "")

            # Buscar template pelo nome
            with _engine.connect() as conn:
                t = conn.execute(text(
                    "SELECT id, prompt FROM templates WHERE name = :n AND category = :c LIMIT 1"
                ), {"n": sub, "c": cat}).first()

            if t:
                prompt_text = t.prompt
                tpl_id = str(t.id)
            else:
                # Fallback: usa o nome como prompt
                prompt_text = f"{sub}, {cat} editorial photography"
                tpl_id = None

            # Adiciona brief se houver (concat com prompt do template)
            if payload.brief:
                prompt_text = f"{prompt_text}. Context: {payload.brief}"

            prompts.append({
                "date": (start + timedelta(days=day - 1)).isoformat(),
                "prompt": prompt_text,
                "template_id": tpl_id,
                "category": cat,
                "sub": sub,
            })
    else:
        raise HTTPException(400, "Forneça pack_key ou custom_prompts")

    if not prompts:
        raise HTTPException(400, "Calendário vazio — verifique pack_key ou custom_prompts")

    # Calcular custo
    cost_per = 8 if not payload.upscale else 13
    total_cost = len(prompts) * cost_per

    if user.credits < total_cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{total_cost})")

    # Criar calendar row
    with _engine.begin() as conn:
        end = (start + timedelta(days=len(prompts) - 1))
        row = conn.execute(text("""
            INSERT INTO content_calendars
              (user_id, persona_id, name, brief, start_date, end_date, pack_key, n_posts,
               status, total_credits_used, posts)
            VALUES (:u, :pid, :n, :b, :sd, :ed, :pk, :np, 'queued', :c, :posts::jsonb)
            RETURNING id
        """), {
            "u": user.user_id, "pid": str(payload.persona_id), "n": payload.name,
            "b": payload.brief, "sd": start, "ed": end, "pk": payload.pack_key,
            "np": len(prompts), "c": total_cost,
            "posts": json.dumps(prompts),
        }).first()
        cid = str(row.id)

    deduct_credits(user.user_id, total_cost)

    # Dispatch worker
    calendar_generate_task.delay(
        calendar_id=cid,
        persona_ref=persona_ref,
        prompts=prompts,
        enhance_skin=payload.enhance_skin,
        upscale=payload.upscale,
    )

    return {
        "id": cid, "n_posts": len(prompts), "total_credits": total_cost,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


@router.get("")
def list_calendars(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM content_calendars WHERE user_id=:u ORDER BY created_at DESC LIMIT 50"
        ), {"u": user.user_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/{calendar_id}")
def get_calendar(calendar_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM content_calendars WHERE id=:id AND user_id=:u"
        ), {"id": calendar_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


@router.delete("/{calendar_id}")
def delete_calendar(calendar_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.begin() as conn:
        r = conn.execute(text(
            "DELETE FROM content_calendars WHERE id=:id AND user_id=:u RETURNING id"
        ), {"id": calendar_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return {"deleted": True}
