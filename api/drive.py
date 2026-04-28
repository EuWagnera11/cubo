"""
Refine — Bulk import de imagens.

Ao invés de Google Drive API, agora aceita:
  - Lista de URLs HTTP públicas (jpg/png/webp)
  - Cada URL é baixada e re-uploadada pro Supabase Storage do user

Usuário pode colar links de qualquer lugar (Pinterest pin, image hosts, S3 público, etc).
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import httpx

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


_IMAGE_EXT = re.compile(r"\.(jpg|jpeg|png|webp|gif)(?:\?|$)", re.IGNORECASE)


async def download_url(url: str) -> tuple[bytes, str]:
    """Baixa imagem de uma URL pública, retorna (bytes, ext)."""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        r = await c.get(url, headers={"User-Agent": "Refine/1.0"})
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").split(";")[0].lower()
        ext = (
            "jpg" if "jpeg" in ct else
            "png" if "png" in ct else
            "webp" if "webp" in ct else
            "gif" if "gif" in ct else
            "jpg"
        )
        return r.content, ext


async def import_url_list(*, urls: list[str], user_id: str, import_id: str) -> dict:
    """
    Baixa cada URL → upload Supabase Storage bucket 'drive-imports'.
    Returns {total, imported, paths}.
    """
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL não configurada")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    total = len(urls)
    if total == 0:
        return {"total": 0, "imported": 0, "paths": []}

    sem = asyncio.Semaphore(5)

    async def fetch_one(idx: int, url: str) -> str | None:
        async with sem:
            try:
                content, ext = await download_url(url)
                storage_path = f"{user_id}/{import_id}/{idx:04d}.{ext}"
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: sb.storage.from_("drive-imports").upload(
                        storage_path, content, file_options={"upsert": "true"}
                    ),
                )
                return storage_path
            except Exception as e:
                print(f"[bulk-import] failed {url[:80]}: {e}")
                return None

    results = await asyncio.gather(*[fetch_one(i, u) for i, u in enumerate(urls)])
    paths = [p for p in results if p]
    return {"total": total, "imported": len(paths), "paths": paths}


# Compat: workers.py ainda chama import_drive_folder
async def import_drive_folder(*, folder_url: str, user_id: str, import_id: str) -> dict:
    """
    Compat wrapper. Antes era Google Drive — agora 'folder_url' é texto multilinha
    com 1 URL por linha (ou separadas por vírgula).
    """
    raw = folder_url.strip()
    urls = [u.strip() for u in re.split(r"[\n,]+", raw) if u.strip()]
    return await import_url_list(urls=urls, user_id=user_id, import_id=import_id)
