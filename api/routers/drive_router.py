"""Bulk imports + style learning + recreate routers.

(Antes era Google Drive — agora aceita lista de URLs públicas direto.)
"""
from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..workers import drive_import_task, style_learn_task, recreate_task

router = APIRouter(prefix="/drive", tags=["bulk-imports"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


class DriveImportCreate(BaseModel):
    """
    Aceita 1 OU 2 formatos:
      - source_urls: ["https://...", ...]   (lista de URLs)
      - source_url:  "url1\nurl2\n..."        (multilinha, 1 por linha)
    """
    source_urls: Optional[list[str]] = None
    source_url: Optional[str] = None
    source_type: str = "manual_upload"
    folder_name: Optional[str] = None


class StyleLearnCreate(BaseModel):
    drive_import_id: UUID
    name: str = Field(..., min_length=2, max_length=100)
    description: str = Field(..., min_length=10, max_length=2000,
                              description="Descreva em texto o estilo a reproduzir (cores, mood, composição, lighting, outfits comuns, etc)")


class RecreateCreate(BaseModel):
    persona_id: UUID
    drive_import_id: UUID
    skin_enhance: bool = True
    magnific: bool = False
    preserve_logos: bool = True


# ─────────────── Drive imports ───────────────

@router.post("/imports")
def create_drive_import(payload: DriveImportCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    # Resolve URLs (lista ou multiline)
    urls: list[str] = []
    if payload.source_urls:
        urls = [u.strip() for u in payload.source_urls if u.strip()]
    elif payload.source_url:
        import re
        urls = [u.strip() for u in re.split(r"[\n,]+", payload.source_url) if u.strip()]
    if not urls:
        raise HTTPException(400, "Forneça pelo menos 1 URL em source_urls ou source_url")

    folder_url_text = "\n".join(urls)
    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO drive_imports (user_id, source_type, source_url, folder_name, total_files, status)
            VALUES (:u, :st, :url, :name, :tot, 'pending') RETURNING id
        """), {
            "u": user.user_id, "st": payload.source_type,
            "url": folder_url_text, "name": payload.folder_name, "tot": len(urls),
        }).first()
        iid = str(row.id)

    drive_import_task.delay(drive_import_id=iid, folder_url=folder_url_text, user_id=user.user_id)
    return {"id": iid, "status": "pending", "url_count": len(urls)}


@router.get("/imports")
def list_imports(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM drive_imports WHERE user_id=:u ORDER BY created_at DESC LIMIT 50"
        ), {"u": user.user_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/imports/{import_id}")
def get_import(import_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM drive_imports WHERE id=:id AND user_id=:u"
        ), {"id": import_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


# ─────────────── Style Learning ───────────────

@router.post("/learn")
def create_learned_style(payload: StyleLearnCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    """
    Style learning manual: user descreve em texto o estilo + lista imagens ref.
    Sistema usa essas refs como reference_images do nano-banana-pro.
    """
    cost = 5  # custo simbólico (sem Claude vision)
    if user.credits < cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{cost})")

    with _engine.connect() as conn:
        imp = conn.execute(text(
            "SELECT storage_paths, status FROM drive_imports WHERE id=:id AND user_id=:u"
        ), {"id": str(payload.drive_import_id), "u": user.user_id}).first()
    if not imp:
        raise HTTPException(404, "Import não encontrado")
    if imp.status != "ready":
        raise HTTPException(400, f"Import ainda não está pronto (status: {imp.status})")
    paths = list(imp.storage_paths or [])
    if len(paths) < 1:
        raise HTTPException(400, f"Pelo menos 1 imagem necessária. Encontradas: {len(paths)}")

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO learned_styles
              (user_id, drive_import_id, name, description, status, prompt_template, example_count, example_paths)
            VALUES (:u, :iid, :n, :d, 'analyzing', '', :ex, :paths) RETURNING id
        """), {
            "u": user.user_id, "iid": str(payload.drive_import_id),
            "n": payload.name, "d": payload.description, "ex": len(paths),
            "paths": "{" + ",".join(paths) + "}",
        }).first()
        sid = str(row.id)

    deduct_credits(user.user_id, cost)
    style_learn_task.delay(
        learned_style_id=sid, image_paths=paths,
        user_description=payload.description, user_id=user.user_id,
    )
    return {"id": sid, "status": "ready", "credits_used": cost}


@router.get("/learn")
def list_learned_styles(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, name, description, status, example_count, created_at FROM learned_styles WHERE user_id=:u ORDER BY created_at DESC"
        ), {"u": user.user_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/learn/{style_id}")
def get_learned_style(style_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM learned_styles WHERE id=:id AND user_id=:u"
        ), {"id": style_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


# ─────────────── Recreate ───────────────

@router.post("/recreate")
def create_recreate(payload: RecreateCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        imp = conn.execute(text(
            "SELECT storage_paths, status FROM drive_imports WHERE id=:id AND user_id=:u"
        ), {"id": str(payload.drive_import_id), "u": user.user_id}).first()
        per = conn.execute(text(
            "SELECT canonical_grid_url, reference_image_url FROM personas WHERE id=:id AND user_id=:u"
        ), {"id": str(payload.persona_id), "u": user.user_id}).first()

    if not imp:
        raise HTTPException(404, "Drive import não encontrado")
    if imp.status != "ready":
        raise HTTPException(400, f"Drive import status: {imp.status}")
    if not per:
        raise HTTPException(404, "Persona não encontrada")

    paths = list(imp.storage_paths or [])
    cost_per = 12 if payload.magnific else 8
    total_cost = len(paths) * cost_per

    if user.credits < total_cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{total_cost})")

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO recreate_jobs
              (user_id, persona_id, drive_import_id, status, total_files, options, total_credits_used)
            VALUES (:u, :pid, :iid, 'queued', :t, :opt::jsonb, :c) RETURNING id
        """), {
            "u": user.user_id, "pid": str(payload.persona_id),
            "iid": str(payload.drive_import_id), "t": len(paths),
            "opt": f'{{"skin_enhance": {str(payload.skin_enhance).lower()}, "magnific": {str(payload.magnific).lower()}, "preserve_logos": {str(payload.preserve_logos).lower()}}}',
            "c": total_cost,
        }).first()
        rid = str(row.id)

    deduct_credits(user.user_id, total_cost)
    recreate_task.delay(
        recreate_job_id=rid,
        persona_id=str(payload.persona_id),
        persona_ref=per.canonical_grid_url or per.reference_image_url,
        drive_import_id=str(payload.drive_import_id),
        options={"skin_enhance": payload.skin_enhance, "magnific": payload.magnific,
                 "preserve_logos": payload.preserve_logos},
    )
    return {"id": rid, "total_files": len(paths), "credits_used": total_cost}


@router.get("/recreate")
def list_recreate(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM recreate_jobs WHERE user_id=:u ORDER BY created_at DESC LIMIT 50"
        ), {"u": user.user_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/recreate/{job_id}")
def get_recreate(job_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM recreate_jobs WHERE id=:id AND user_id=:u"
        ), {"id": job_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)
