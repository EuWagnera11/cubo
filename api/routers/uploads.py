"""Upload helpers.

POST /uploads/file        — multipart upload direto pra VPS (recomendado).
                            Retorna URL pública servida pela própria API
                            (Kling/Veo/etc baixam sem token).

POST /uploads/signed-url  — legado: signed URL Supabase pra browser PUT direto.
                            Mantido pra compat, mas Kling não consegue baixar
                            URLs Supabase signed (usa /file em vez disso).
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..auth_dep import get_current_user, AuthUser

router = APIRouter(prefix="/uploads", tags=["uploads"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/code/uploads")
PUBLIC_API_URL = os.environ.get("PUBLIC_API_URL", "https://cubo-api.173-212-246-67.sslip.io").rstrip("/")
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov"}
MAX_BYTES = 25 * 1024 * 1024  # 25 MB


@router.post("/file")
async def upload_file_to_vps(
    file: UploadFile = File(...),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    """Recebe multipart upload, salva no disco da VPS, retorna URL pública.

    URL retornada é servida via StaticFiles em /static/uploads/<user>/<file>.
    Kling/Veo/etc conseguem baixar diretamente (sem token, sem auth).
    """
    name = file.filename or "file"
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTS:
        # Tenta inferir do content_type
        ct = (file.content_type or "").lower()
        if "jpeg" in ct or "jpg" in ct: ext = ".jpg"
        elif "png" in ct: ext = ".png"
        elif "webp" in ct: ext = ".webp"
        elif "mp4" in ct: ext = ".mp4"
        else: ext = ".bin"

    safe_id = uuid.uuid4().hex[:16]
    filename = f"{safe_id}{ext}"

    user_dir = os.path.join(UPLOAD_DIR, str(user.user_id))
    os.makedirs(user_dir, exist_ok=True)
    fpath = os.path.join(user_dir, filename)

    # Stream pra disco com limite de tamanho
    total = 0
    with open(fpath, "wb") as f:
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                f.close()
                os.remove(fpath)
                raise HTTPException(413, f"Arquivo > {MAX_BYTES // (1024*1024)} MB")
            f.write(chunk)

    public_url = f"{PUBLIC_API_URL}/static/uploads/{user.user_id}/{filename}"
    return {
        "url": public_url,
        "path": f"{user.user_id}/{filename}",
        "size": total,
        "content_type": file.content_type or f"image/{ext.strip('.')}",
    }


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

    # Prefixa filename com UUID curto pra evitar 409 Duplicate quando o mesmo
    # arquivo for enviado mais de uma vez. Mantém extensão pra preview/MIME OK.
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", payload.filename) or "file.bin"
    storage_path = f"{user.user_id}/{uuid.uuid4().hex[:12]}_{safe_name}"
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
