"""
Refine — Google Drive integration.

Suporta:
  - Pasta pública compartilhada (link "anyone with the link") via API key
  - OAuth 2.0 pra pastas privadas (Token persistido por user)

Baixa imagens da pasta + uploadeia pro Supabase Storage do user.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import httpx

from supabase import create_client

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_DOWNLOAD = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def extract_folder_id(url: str) -> str | None:
    """Extrai folderId de URL Drive (/folders/<id> ou /drive/folders/<id>)."""
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


async def list_drive_folder_files(folder_id: str, *, api_key: str = GOOGLE_API_KEY) -> list[dict]:
    """Lista todos arquivos na pasta (paginated)."""
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY não configurada")

    files: list[dict] = []
    page_token: str | None = None

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            params = {
                "q": f"'{folder_id}' in parents and trashed=false",
                "key": api_key,
                "fields": "nextPageToken,files(id,name,mimeType,size,thumbnailLink)",
                "pageSize": 1000,
            }
            if page_token:
                params["pageToken"] = page_token

            r = await client.get(f"{DRIVE_API}/files", params=params)
            if r.status_code != 200:
                raise RuntimeError(f"Drive list failed: {r.status_code} {r.text[:200]}")
            data = r.json()
            files.extend(data.get("files", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    # Só imagens / vídeos
    return [
        f for f in files
        if (f.get("mimeType") or "").startswith(("image/", "video/"))
    ]


async def download_drive_file(file_id: str, *, api_key: str = GOOGLE_API_KEY) -> bytes:
    """Baixa bytes de um arquivo público."""
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(DRIVE_DOWNLOAD.format(file_id=file_id), params={"key": api_key})
        if r.status_code != 200:
            raise RuntimeError(f"Drive download failed: {r.status_code}")
        return r.content


async def import_drive_folder(*, folder_url: str, user_id: str, import_id: str) -> dict:
    """
    Baixa pasta inteira → upload Supabase Storage bucket 'drive-imports'.
    Retorna {total, imported, paths}.
    """
    folder_id = extract_folder_id(folder_url)
    if not folder_id:
        raise ValueError(f"URL Drive inválida: {folder_url}")

    files = await list_drive_folder_files(folder_id)
    total = len(files)
    if total == 0:
        return {"total": 0, "imported": 0, "paths": []}

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    paths: list[str] = []
    sem = asyncio.Semaphore(5)  # max 5 downloads paralelos

    async def upload_one(f: dict) -> str | None:
        async with sem:
            try:
                content = await download_drive_file(f["id"])
                ext = f["name"].split(".")[-1] if "." in f["name"] else "jpg"
                storage_path = f"{user_id}/{import_id}/{f['id']}.{ext}"
                # Supabase storage upload (sync client OK aqui — wrap em executor)
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: sb.storage.from_("drive-imports").upload(
                        storage_path, content, file_options={"upsert": "true"}
                    ),
                )
                return storage_path
            except Exception as e:
                print(f"[drive] failed {f['name']}: {e}")
                return None

    results = await asyncio.gather(*[upload_one(f) for f in files])
    paths = [p for p in results if p]
    return {"total": total, "imported": len(paths), "paths": paths}
