"""
Refine — Gerador batch de previews pra TODOS templates, presets, worlds, tools.

Lê do Supabase/Postgres, gera 1 preview pra cada item via Freepik (nano-banana-pro 2K),
upload no Supabase Storage bucket 'previews' e atualiza preview_url no DB.

Custo estimado:
  - 200+ templates × ~$0.08 = $16
  - 30 model presets  × ~$0.08 = $2.4
  - 40 worlds          × ~$0.08 = $3.2
  Total: ~$22 (R$ 110)

Uso:
  python tools/gen_all_previews.py --target templates  # só templates
  python tools/gen_all_previews.py --target all        # tudo
  python tools/gen_all_previews.py --target presets --limit 5  # teste
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text
from supabase import create_client

# Importar cliente Freepik do api/
sys.path.insert(0, str(Path(__file__).parent.parent))
from api.freepik import FreepikClient

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
FREEPIK_KEYS = [k.strip() for k in os.environ.get("FREEPIK_API_KEYS", "").split(",") if k.strip()]

CONCURRENCY = 3        # Freepik suporta multiple paralelos, mas conservador
DEFAULT_PROMPT_SUFFIX = ", editorial photography, 4K quality, professional lighting"


def make_engine():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não configurada")
    return create_engine(DATABASE_URL.replace("+asyncpg", ""), pool_pre_ping=True)


def make_supabase():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL/SUPABASE_SERVICE_KEY não configurados")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


async def download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


async def gen_one(fp: FreepikClient, prompt: str, *, ratio: str = "portrait_4_5") -> str | None:
    """Gera 1 imagem via nano-banana-pro 2K. Retorna URL gerada."""
    full = f"{prompt}{DEFAULT_PROMPT_SUFFIX}"
    try:
        task_id = await fp.nano_banana_pro(prompt=full, aspect_ratio=ratio, size="2k")
        result = await fp.poll_task(task_id, kind="image", max_wait_s=300)
        urls = result.get("generated") or result.get("urls") or []
        if isinstance(urls, str):
            return urls
        return urls[0] if urls else None
    except Exception as e:
        print(f"  [ERR] {prompt[:60]}... → {e}")
        return None


async def upload_preview(sb, image_bytes: bytes, kind: str, item_id: str) -> str | None:
    """Upload pra bucket 'previews' e retorna URL pública."""
    path = f"{kind}/{item_id}.jpg"
    try:
        sb.storage.from_("previews").upload(path, image_bytes,
            file_options={"content-type": "image/jpeg", "upsert": "true"})
        return sb.storage.from_("previews").get_public_url(path)
    except Exception as e:
        print(f"  [UPLOAD ERR] {path} → {e}")
        return None


async def process_item(fp, sb, sem, *, table: str, id_col: str, id_val: str,
                       prompt: str, name: str, ratio: str = "portrait_4_5"):
    """Gera + upload + update DB."""
    async with sem:
        print(f"  → {name[:60]}")
        gen_url = await gen_one(fp, prompt, ratio=ratio)
        if not gen_url:
            return False

        try:
            img_bytes = await download(gen_url)
        except Exception as e:
            print(f"  [DOWNLOAD ERR] {e}")
            return False

        preview_url = await upload_preview(sb, img_bytes, table, id_val)
        if not preview_url:
            return False

        # Update DB
        engine = make_engine()
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE {table} SET preview_url = :url WHERE {id_col} = :id"),
                         {"url": preview_url, "id": id_val})
        print(f"    ✓ {preview_url}")
        return True


async def gen_for_templates(fp, sb, *, limit: int | None = None, only_missing: bool = True):
    engine = make_engine()
    q = "SELECT id, name, prompt, media_type FROM templates WHERE is_public = true"
    if only_missing:
        q += " AND (preview_url IS NULL OR preview_url LIKE '/placeholder%')"
    q += " ORDER BY uses_count DESC NULLS LAST"
    if limit:
        q += f" LIMIT {limit}"

    with engine.connect() as conn:
        rows = conn.execute(text(q)).fetchall()

    print(f"\n📷 Gerando previews pra {len(rows)} templates...")
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [
        process_item(fp, sb, sem,
                     table="templates", id_col="id", id_val=str(r.id),
                     prompt=r.prompt or r.name, name=r.name,
                     ratio="social_story_9_16" if r.media_type == "video" else "portrait_4_5")
        for r in rows
    ]
    results = await asyncio.gather(*tasks)
    print(f"\n✅ Templates: {sum(results)}/{len(rows)} success")


async def gen_for_presets(fp, sb, *, limit: int | None = None, only_missing: bool = True):
    engine = make_engine()
    q = "SELECT id, name, base_prompt FROM model_presets"
    if only_missing:
        q += " WHERE reference_image_url LIKE '/presets%'"
    q += " ORDER BY uses_count DESC NULLS LAST"
    if limit:
        q += f" LIMIT {limit}"

    with engine.connect() as conn:
        rows = conn.execute(text(q)).fetchall()

    print(f"\n👤 Gerando previews pra {len(rows)} model presets...")
    sem = asyncio.Semaphore(CONCURRENCY)

    async def proc_preset(r):
        async with sem:
            print(f"  → {r.name}")
            url = await gen_one(fp, f"{r.base_prompt}, full body editorial portrait, neutral background", ratio="portrait_4_5")
            if not url: return False
            try:
                img = await download(url)
                pub = await upload_preview(sb, img, "presets", str(r.id))
                if pub:
                    eng = make_engine()
                    with eng.begin() as conn:
                        conn.execute(text("UPDATE model_presets SET reference_image_url = :u WHERE id = :id"),
                                     {"u": pub, "id": str(r.id)})
                    print(f"    ✓ {pub}")
                    return True
            except Exception as e:
                print(f"  [ERR] {e}")
            return False

    results = await asyncio.gather(*[proc_preset(r) for r in rows])
    print(f"\n✅ Presets: {sum(results)}/{len(rows)} success")


async def gen_for_worlds(fp, sb, *, limit: int | None = None, only_missing: bool = True):
    engine = make_engine()
    q = "SELECT id, name, prompt_template FROM worlds WHERE is_public = true"
    if only_missing:
        q += " AND preview_url IS NULL"
    q += " ORDER BY uses_count DESC NULLS LAST"
    if limit:
        q += f" LIMIT {limit}"

    with engine.connect() as conn:
        rows = conn.execute(text(q)).fetchall()

    print(f"\n🌍 Gerando previews pra {len(rows)} worlds...")
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [
        process_item(fp, sb, sem, table="worlds", id_col="id", id_val=str(r.id),
                     prompt=r.prompt_template, name=r.name, ratio="widescreen_16_9")
        for r in rows
    ]
    results = await asyncio.gather(*tasks)
    print(f"\n✅ Worlds: {sum(results)}/{len(rows)} success")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["templates", "presets", "worlds", "all"], default="all")
    ap.add_argument("--limit", type=int, default=None, help="Limita N items pra teste")
    ap.add_argument("--all", action="store_true", help="Regerar todos (não só missing)")
    args = ap.parse_args()

    if not FREEPIK_KEYS:
        print("❌ FREEPIK_API_KEYS não configurada")
        sys.exit(1)

    fp = FreepikClient(api_keys=FREEPIK_KEYS)
    sb = make_supabase()

    only_missing = not args.all

    t0 = time.time()
    try:
        if args.target in ("templates", "all"):
            await gen_for_templates(fp, sb, limit=args.limit, only_missing=only_missing)
        if args.target in ("presets", "all"):
            await gen_for_presets(fp, sb, limit=args.limit, only_missing=only_missing)
        if args.target in ("worlds", "all"):
            await gen_for_worlds(fp, sb, limit=args.limit, only_missing=only_missing)
    finally:
        await fp.close()

    dt = time.time() - t0
    print(f"\n⏱️  Total: {dt:.1f}s ({dt/60:.1f}min)")


if __name__ == "__main__":
    asyncio.run(main())
