"""Admin router — operações privilegiadas e diagnóstico.

Protegido por header X-Admin-Key (configurado em env ADMIN_API_KEY).
"""
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from ..workers import regen_previews_task, celery_app

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_engine = create_engine(DATABASE_URL.replace("+asyncpg", ""), pool_pre_ping=True) if DATABASE_URL else None


def _check_admin(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    if not ADMIN_KEY:
        raise HTTPException(503, "ADMIN_API_KEY não configurada")
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(403, "Admin key inválida")
    return True


# ════════════════════════════════════════════════════════════════
#                       DIAG / OBSERVABILITY
# ════════════════════════════════════════════════════════════════

@router.get("/diag")
def diag(_=Depends(_check_admin)) -> dict:
    """Estado geral: workers conectados, fila Celery, jobs recentes."""
    out: dict = {
        "redis_url_set": bool(os.environ.get("REDIS_URL")),
        "freepik_keys": len([k for k in os.environ.get("FREEPIK_API_KEYS", "").split(",") if k.strip()]),
        "service_mode": os.environ.get("SERVICE_MODE", "api"),
    }

    # Celery: workers conectados + tasks
    try:
        i = celery_app.control.inspect(timeout=3.0)
        out["celery_workers_ping"] = i.ping() or {}
        out["celery_active"] = i.active() or {}
        out["celery_reserved"] = i.reserved() or {}
        stats = i.stats() or {}
        out["celery_stats_summary"] = {
            name: {
                "total": s.get("total", {}),
                "pool_max_concurrency": s.get("pool", {}).get("max-concurrency"),
            } for name, s in stats.items()
        }
    except Exception as e:
        out["celery_error"] = str(e)[:300]

    # DB: jobs recentes
    if _engine:
        try:
            with _engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT status, COUNT(*) AS n
                    FROM generations
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                    GROUP BY status
                """)).fetchall()
                out["jobs_last_hour_by_status"] = {r.status: r.n for r in rows}

                stuck = conn.execute(text("""
                    SELECT id, status, error_message, created_at
                    FROM generations
                    WHERE status IN ('queued','processing')
                      AND created_at < NOW() - INTERVAL '5 minutes'
                    ORDER BY created_at DESC LIMIT 10
                """)).fetchall()
                out["stuck_jobs"] = [
                    {"id": str(r.id), "status": r.status, "error": r.error_message,
                     "created_at": str(r.created_at)} for r in stuck
                ]
        except Exception as e:
            out["db_error"] = str(e)[:300]

    return out


@router.get("/job/{generation_id}")
def get_job_detail(generation_id: str, _=Depends(_check_admin)) -> dict:
    """Detalhe completo de uma generation."""
    if not _engine:
        raise HTTPException(503, "DB não configurado")
    with _engine.connect() as conn:
        r = conn.execute(text("SELECT * FROM generations WHERE id=:id"),
                         {"id": generation_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


@router.get("/recent-failures")
def recent_failures(limit: int = 20, _=Depends(_check_admin)) -> list[dict]:
    """Últimas falhas com error_message — pra debug."""
    if not _engine:
        raise HTTPException(503, "DB não configurado")
    with _engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, user_id, status, error_message, prompt, media_type,
                   credits_used, created_at
            FROM generations
            WHERE status = 'failed'
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
    return [
        {"id": str(r.id), "user_id": str(r.user_id), "status": r.status,
         "error": r.error_message, "prompt": (r.prompt or "")[:200],
         "media_type": r.media_type, "credits_used": r.credits_used,
         "created_at": str(r.created_at)}
        for r in rows
    ]


# ════════════════════════════════════════════════════════════════
#                       OPERATIONS (refund)
# ════════════════════════════════════════════════════════════════

class RefundReq(BaseModel):
    generation_id: str
    reason: Optional[str] = None


@router.post("/refund")
def refund_generation(payload: RefundReq, _=Depends(_check_admin)) -> dict:
    """Devolve créditos de uma generation falhada pro user."""
    if not _engine:
        raise HTTPException(503, "DB não configurado")
    with _engine.begin() as conn:
        gen = conn.execute(text("""
            SELECT user_id, credits_used, status FROM generations WHERE id=:id
        """), {"id": payload.generation_id}).first()
        if not gen:
            raise HTTPException(404, "Generation não encontrada")
        if gen.credits_used <= 0:
            return {"refunded": 0, "reason": "no credits to refund"}

        conn.execute(text("UPDATE profiles SET credits = credits + :n WHERE id = :uid"),
                     {"n": gen.credits_used, "uid": gen.user_id})
        conn.execute(text("""
            UPDATE generations SET credits_used = 0,
                   error_message = COALESCE(error_message, '') || ' [refunded]'
            WHERE id = :id
        """), {"id": payload.generation_id})

    return {"refunded": gen.credits_used, "user_id": str(gen.user_id),
            "generation_id": payload.generation_id, "reason": payload.reason}


@router.post("/refund-all-failed")
def refund_all_failed_recent(hours: int = 24, _=Depends(_check_admin)) -> dict:
    """Refund de todas as failures não-refundidas das últimas X horas."""
    if not _engine:
        raise HTTPException(503)
    refunded_total = 0
    affected = 0
    with _engine.begin() as conn:
        gens = conn.execute(text("""
            SELECT id, user_id, credits_used FROM generations
            WHERE status = 'failed'
              AND credits_used > 0
              AND COALESCE(error_message, '') NOT LIKE '%[refunded]%'
              AND created_at > NOW() - (:h || ' hours')::interval
        """), {"h": str(hours)}).fetchall()

        for g in gens:
            conn.execute(text("UPDATE profiles SET credits = credits + :n WHERE id = :u"),
                         {"n": g.credits_used, "u": g.user_id})
            conn.execute(text("""
                UPDATE generations SET credits_used = 0,
                       error_message = COALESCE(error_message, '') || ' [refunded]'
                WHERE id = :id
            """), {"id": g.id})
            refunded_total += g.credits_used
            affected += 1

    return {"refunded_total": refunded_total, "jobs_affected": affected, "hours": hours}


# ════════════════════════════════════════════════════════════════
#                       REGEN PREVIEWS (existente)
# ════════════════════════════════════════════════════════════════

class RegenReq(BaseModel):
    target: Literal["templates", "presets", "worlds", "all"] = "all"
    limit: Optional[int] = None


@router.post("/regen-previews")
def trigger_regen(payload: RegenReq, _=Depends(_check_admin)) -> dict:
    task = regen_previews_task.delay(target=payload.target, limit=payload.limit)
    return {"status": "queued", "task_id": task.id, "target": payload.target,
            "limit": payload.limit}


@router.get("/health")
def admin_health(_=Depends(_check_admin)) -> dict:
    return {"status": "ok", "admin": True}
