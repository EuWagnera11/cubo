"""Admin router — operações privilegiadas (regen previews, etc).

Protegido por header X-Admin-Key (configurado em env ADMIN_API_KEY).
"""
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from ..workers import regen_previews_task

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "")


def _check_admin(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    if not ADMIN_KEY:
        raise HTTPException(503, "ADMIN_API_KEY não configurada")
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(403, "Admin key inválida")
    return True


class RegenReq(BaseModel):
    target: Literal["templates", "presets", "worlds", "all"] = "all"
    limit: Optional[int] = None


@router.post("/regen-previews")
def trigger_regen(payload: RegenReq, _=Depends(_check_admin)) -> dict:
    """
    Dispara worker pra regenerar previews de todos templates/presets/worlds.
    Custo estimado: ~$0.08 por imagem × ~270 items = ~$22 (R$110).
    """
    task = regen_previews_task.delay(target=payload.target, limit=payload.limit)
    return {
        "status": "queued",
        "task_id": task.id,
        "target": payload.target,
        "limit": payload.limit,
        "message": "Worker rodando. Acompanhe via logs do refine-worker.",
    }


@router.get("/health")
def admin_health(_=Depends(_check_admin)) -> dict:
    return {"status": "ok", "admin": True}
