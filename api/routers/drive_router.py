"""Drive imports + style learning + recreate routers."""
from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..workers import drive_import_task, style_learn_task, recreate_task
from ..drive import extract_folder_id

router = APIRouter(prefix="/drive", tags=["drive"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


class DriveImportCreate(BaseModel):
    source_url: HttpUrl
    source_type: str = "google_drive"
    folder_name: Optional[str] = None


class StyleLearnCreate(BaseModel):
    drive_import_id: UUID
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None


class RecreateCreate(BaseModel):
    persona_id: UUID
    drive_import_id: UUID
    skin_enhance: bool = True
    magnific: bool = False
    preserve_logos: bool = True


# ─────────────── Drive imports ───────────────

@router.post("/imports")
def create_drive_import(payload: DriveImportCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    if payload.source_type == "google_drive":
        if not extract_folder_id(str(payload.source_url)):
            raise HTTPException(400, "URL Google Drive inválida (formato esperado: /folders/<id>)")

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO drive_imports (user_id, source_type, source_url, folder_name, status)
            VALUES (:u, :st, :url, :name, 'pending') RETURNING id
        """), {
            "u": user.user_id, "st": payload.source_type,
            "url": str(payload.source_url), "name": payload.folder_name,
        }).first()
        iid = str(row.id)

    drive_import_task.delay(drive_import_id=iid, folder_url=str(payload.source_url), user_id=user.user_id)
    return {"id": iid, "status": "pending"}


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
    cost = 30  # 1 análise vision = 30 créditos (Claude Opus 4.7 vision é caro)
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
    if len(paths) < 5:
        raise HTTPException(400, f"Mínimo 5 imagens. Encontradas: {len(paths)}")

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
    style_learn_task.delay(learned_style_id=sid, image_paths=paths, user_id=user.user_id)
    return {"id": sid, "status": "analyzing", "credits_used": cost}


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
