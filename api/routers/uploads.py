"""Upload helpers — signed URLs pro Supabase Storage.

Usa a Storage REST API direto via httpx (mais robusto do que supabase-py,
que muda assinatura de retorno entre versões — `create_signed_upload_url`
às vezes retorna chave 'url', às vezes 'signedUrl', etc).
"""
from __future__ import annotations

import os
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth_dep import get_current_user, AuthUser

router = APIRouter(prefix="/uploads", tags=["uploads"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


class SignedUploadReq(BaseModel):
    bucket: Literal["avatars", "personas", "generation-refs", "drive-imports"]
    filename: str
    content_type: str = "image/jpeg"


def _service_headers() -> dict:
    return {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "application/json",
    }


@router.post("/signed-url")
def create_signed_upload(payload: SignedUploadReq, user: AuthUser = Depends(get_current_user)) -> dict:
    """Gera signed URL pra upload direto pro Supabase (browser PUTa direto)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(503, "Supabase storage não configurado")

    storage_path = f"{user.user_id}/{payload.filename}"
    endpoint = f"{SUPABASE_URL}/storage/v1/object/upload/sign/{payload.bucket}/{storage_path}"

    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.post(endpoint, headers=_service_headers(), json={})
        if r.status_code >= 400:
            raise HTTPException(r.status_code, f"Supabase storage error: {r.text[:300]}")
        data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(500, f"Storage HTTP error: {e}")

    # Resposta atual do Supabase: {"url": "/object/upload/sign/<bucket>/<path>?token=...", "token": "..."}
    rel_url = data.get("url") or data.get("signedURL") or data.get("signedUrl") or data.get("signed_url")
    if not rel_url:
        raise HTTPException(500, f"Supabase did not return signed URL: {data}")
    upload_url = f"{SUPABASE_URL}/storage/v1{rel_url}" if rel_url.startswith("/") else rel_url

    return {
        "upload_url": upload_url,
        "token": data.get("token"),
        "path": storage_path,
        "bucket": payload.bucket,
    }


@router.post("/signed-download")
def create_signed_download(bucket: str, path: str, ttl: int = 3600,
                            user: AuthUser = Depends(get_current_user)) -> dict:
    """Signed URL pra download (assets privados como personas/drive-imports)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(503, "Supabase storage não configurado")

    endpoint = f"{SUPABASE_URL}/storage/v1/object/sign/{bucket}/{path}"
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.post(endpoint, headers=_service_headers(), json={"expiresIn": ttl})
        if r.status_code >= 400:
            raise HTTPException(r.status_code, f"Supabase storage error: {r.text[:300]}")
        data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(500, f"Storage HTTP error: {e}")

    rel = data.get("signedURL") or data.get("signedUrl") or data.get("url")
    if not rel:
        raise HTTPException(500, f"Supabase did not return signed URL: {data}")
    full = f"{SUPABASE_URL}/storage/v1{rel}" if rel.startswith("/") else rel
    return {"url": full}
