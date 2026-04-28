"""Upload helpers — signed URLs pro Supabase Storage."""
from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import create_client

from ..auth_dep import get_current_user, AuthUser

router = APIRouter(prefix="/uploads", tags=["uploads"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


class SignedUploadReq(BaseModel):
    bucket: Literal["avatars", "personas", "generation-refs", "drive-imports"]
    filename: str
    content_type: str = "image/jpeg"


@router.post("/signed-url")
def create_signed_upload(payload: SignedUploadReq, user: AuthUser = Depends(get_current_user)) -> dict:
    """Gera signed URL pra upload direto pro Supabase (browser POSTa direto)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(503, "Supabase storage não configurado")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    storage_path = f"{user.user_id}/{payload.filename}"
    try:
        res = sb.storage.from_(payload.bucket).create_signed_upload_url(storage_path)
    except Exception as e:
        raise HTTPException(500, f"Storage error: {e}")
    return {
        "upload_url": res.get("signedUrl") or res.get("signed_url"),
        "token": res.get("token"),
        "path": storage_path,
        "bucket": payload.bucket,
    }


@router.post("/signed-download")
def create_signed_download(bucket: str, path: str, ttl: int = 3600,
                            user: AuthUser = Depends(get_current_user)) -> dict:
    """Signed URL pra download (avatares privados, etc)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(503)
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    try:
        res = sb.storage.from_(bucket).create_signed_url(path, ttl)
    except Exception as e:
        raise HTTPException(500, f"Storage error: {e}")
    return {"url": res.get("signedURL") or res.get("signedUrl")}
