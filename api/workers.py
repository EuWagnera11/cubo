"""
Refine — Celery workers.

Tasks long-running:
  - generate_image     : nano-banana / mystic / flux + enhancers
  - generate_video     : kling / hailuo / wan
  - face_swap_job      : face swap em batch
  - scene_swap_job     : muda cenário preservando persona
  - cloth_swap_job     : muda outfit
  - batch_image_job    : N imagens em paralelo
  - batch_video_job    : N vídeos
  - drive_import_job   : baixa pasta Google Drive → storage
  - style_learn_job    : analisa N imgs com Claude Opus 4.7 → learned_style
  - recreate_job       : recria fotos do drive com persona do user

Celery + Redis broker. Cada task atualiza status no Postgres.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from celery import Celery
from sqlalchemy import create_engine, text

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/refine")

celery_app = Celery("refine", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Sao_Paulo",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=900,         # 15min hard limit
    task_soft_time_limit=840,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    # Robustness: reconectar automaticamente se broker cair, heartbeat
    # pra detectar conexao zombie. Evita worker "vivo mas surdo".
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=None,  # infinite retries
    broker_heartbeat=10,
    broker_heartbeat_checkrate=2.0,
    broker_pool_limit=None,  # cria conexao on demand, evita pool stale
    # Worker: reconectar se ficar idle muito tempo
    worker_cancel_long_running_tasks_on_connection_loss=True,
    # Visibility timeout no Redis: se worker morrer no meio de uma task,
    # outro worker pega depois desse tempo (default = 1h, baixar p/ 15min)
    broker_transport_options={"visibility_timeout": 900},
    result_backend_transport_options={"visibility_timeout": 900},
)

# Celery Beat schedule — tarefas periódicas
celery_app.conf.beat_schedule = {
    # Limpa registros de daily_usage > 7 dias (todo dia, 04:00)
    "cleanup-daily-usage": {
        "task": "refine.cleanup_daily_usage",
        "schedule": {"hour": 4, "minute": 0},
    },
    # Anuais NÃO precisam de cron de reposição — créditos são liberados
    # de uma vez via invoice.paid (Stripe dispara renovação anual sozinho).
}

# Sync engine pra workers (Celery não trabalha bem com asyncio)
engine = create_engine(DATABASE_URL.replace("+asyncpg", ""), pool_pre_ping=True)


def _run(coro):
    """Roda async fn em Celery worker (cria event loop temp)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _update_generation(generation_id: str, **fields):
    """Update generations table com fields passados."""
    if not fields:
        return
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = generation_id
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE generations SET {sets} WHERE id = :id"), fields)


def _update_batch(batch_id: str, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = batch_id
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE batch_jobs SET {sets} WHERE id = :id"), fields)


# ════════════════════════════════════════════════════════════════
#                    IMAGE GENERATION
# ════════════════════════════════════════════════════════════════

@celery_app.task(name="refine.generate_image", bind=True, max_retries=2)
def generate_image_task(
    self,
    *,
    generation_id: str,
    prompt: str,
    persona_ref_url: str | None = None,
    template_prompt: str | None = None,
    aspect_ratio: str = "square_4_5",
    resolution: str = "2k",
    num_variations: int = 4,
    enhance_skin: bool = True,
    upscale: bool = False,
    model: str = "nano-banana-pro",
) -> dict:
    """
    Pipeline completo (dispatch dinâmico baseado em `model`):
      1. modelo escolhido pelo user (nano-banana-pro / mystic / flux / imagen / etc)
      2. skin_enhancer faithful (combate plastic look)
      3. magnific_upscaler (opcional)
      4. salva URLs no DB
    """
    from .freepik import get_freepik, FreepikError
    from .model_router import resolve_image_method, call_with_supported_kwargs

    fp = get_freepik()
    full_prompt = f"{template_prompt}. {prompt}".strip(". ").strip() if template_prompt else prompt
    refs = [persona_ref_url] if persona_ref_url else None

    method_name = resolve_image_method(model)
    fn = getattr(fp, method_name, None)
    if fn is None:
        # Fallback seguro: nano-banana-pro sempre existe
        method_name = "nano_banana_pro"
        fn = fp.nano_banana_pro

    try:
        _update_generation(generation_id, status="processing")

        # 1. Generate base — dispatch dinâmico
        urls: list[str] = []
        for i in range(num_variations):
            task_id = _run(call_with_supported_kwargs(
                fn,
                prompt=full_prompt,
                reference_images=refs,
                aspect_ratio=aspect_ratio,
                size=resolution,           # nano-banana family
                resolution=resolution,     # outros que aceitam "resolution"
                num_images=1,              # imagen family
            ))
            result = _run(fp.poll_task(task_id, kind="image", max_wait_s=300))
            generated = result.get("generated") or result.get("urls") or []
            if isinstance(generated, str):
                generated = [generated]
            urls.extend(generated)

        # 2. Skin enhance (opcional, falha gracefully se Freepik 404)
        if enhance_skin and urls:
            _update_generation(generation_id, status="enhancing")
            enhanced: list[str] = []
            for u in urls:
                try:
                    t = _run(fp.skin_enhancer(u, mode="faithful", skin_detail=20, smart_grain=0))
                    r = _run(fp.poll_task(t, kind="enhance", max_wait_s=180))
                    enhanced.append(r.get("generated", [u])[0] if isinstance(r.get("generated"), list) else (r.get("generated") or u))
                except Exception as e:
                    print(f"[worker] skin_enhancer falhou (mantendo imagem original): {e}")
                    enhanced.append(u)  # mantem imagem crua se enhancer 404
            urls = enhanced

        # 3. Upscale (opcional, falha gracefully)
        if upscale and urls:
            _update_generation(generation_id, status="upscaling")
            upscaled: list[str] = []
            for u in urls:
                try:
                    t = _run(fp.magnific_upscaler(u, scale=2, engine="magnific_sparkle", engine_style="soft_portraits"))
                    r = _run(fp.poll_task(t, kind="enhance", max_wait_s=300))
                    upscaled.append(r.get("generated", [u])[0] if isinstance(r.get("generated"), list) else (r.get("generated") or u))
                except Exception as e:
                    print(f"[worker] magnific_upscaler falhou (mantendo imagem original): {e}")
                    upscaled.append(u)
            urls = upscaled

        _update_generation(
            generation_id,
            status="completed",
            image_urls="{" + ",".join(urls) + "}",
            completed_at="now()",
        )
        return {"status": "completed", "urls": urls}

    except (FreepikError, Exception) as e:
        _update_generation(generation_id, status="failed", error_message=str(e)[:1000])
        raise self.retry(exc=e, countdown=10)


# ════════════════════════════════════════════════════════════════
#                    VIDEO GENERATION
# ════════════════════════════════════════════════════════════════

@celery_app.task(name="refine.generate_video", bind=True, max_retries=1)
def generate_video_task(
    self,
    *,
    generation_id: str,
    image_url: str,
    prompt: str,
    engine: str = "kling_v3",
    duration: str = "5",
    fallback_to: str = "kling_v2_1",
) -> dict:
    """Image-to-video com fallback automático em caso de cap."""
    from .freepik import get_freepik, FreepikError, FreepikQuotaExceeded
    from .model_router import resolve_video_method, call_with_supported_kwargs

    fp = get_freepik()
    try:
        _update_generation(generation_id, status="processing")

        # Kling/Veo/etc da Magnific NAO conseguem baixar URLs Supabase signed
        # (ignoram silenciosamente e fazem text-to-video). Converte URL -> data URI
        # antes de mandar pra API. Custo: 1 GET extra + ~70KB de base64 no body.
        if image_url and image_url.startswith("http"):
            try:
                image_url = _run(fp._fetch_to_data_uri(image_url))
                print(f"[generate_video] image baixada e convertida pra data URI ({len(image_url)} chars)", flush=True)
            except Exception as e:
                print(f"[generate_video] falha ao baixar image_url: {e}. Tentando enviar URL original.", flush=True)

        # Normaliza IDs com hífen (ex: "kling-v3-std") -> nome de método ("kling_v3")
        primary = resolve_video_method(engine)
        secondary = resolve_video_method(fallback_to)
        engines_chain = [primary, secondary, "hailuo", "kling_v2_6"]
        # Remove duplicatas mantendo ordem
        seen = set()
        engines_chain = [e for e in engines_chain if not (e in seen or seen.add(e))]

        last_err = None
        # Normaliza duration: API Magnific aceita só "5" ou "10" (sem sufixo "s")
        norm_duration = (duration or "5").rstrip("s ") or "5"
        for eng in engines_chain:
            fn = getattr(fp, eng, None)
            if fn is None:
                continue
            try:
                task_id = _run(call_with_supported_kwargs(
                    fn, image_url=image_url, prompt=prompt, duration=norm_duration,
                ))
                result = _run(fp.poll_task(task_id, kind="video", max_wait_s=600))
                video_urls = result.get("generated") or result.get("urls") or []
                if isinstance(video_urls, str):
                    video_urls = [video_urls]
                _update_generation(
                    generation_id,
                    status="completed",
                    video_urls="{" + ",".join(video_urls) + "}",
                    completed_at="now()",
                )
                return {"status": "completed", "urls": video_urls, "engine_used": eng}
            except FreepikQuotaExceeded as e:
                last_err = e
                continue

        _update_generation(generation_id, status="failed", error_message=str(last_err or "All video engines quota exceeded")[:1000])
        raise (last_err or FreepikError("All video engines quota exceeded"))

    except FreepikError as e:
        _update_generation(generation_id, status="failed", error_message=str(e)[:1000])
        raise self.retry(exc=e, countdown=30)


# ════════════════════════════════════════════════════════════════
#                    SWAPS (face / scene / cloth)
# ════════════════════════════════════════════════════════════════

@celery_app.task(name="refine.face_swap", bind=True)
def face_swap_task(self, *, generation_id: str, source_image: str, target_image: str) -> dict:
    """Face swap + skin enhance pra naturalidade."""
    from .freepik import get_freepik, FreepikError
    fp = get_freepik()
    try:
        _update_generation(generation_id, status="processing")
        task_id = _run(fp.face_swap(source_image, target_image))
        result = _run(fp.poll_task(task_id, kind="image", max_wait_s=240))
        urls = result.get("generated") or result.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]

        # Skin enhance pós-swap (combate seam)
        _update_generation(generation_id, status="enhancing")
        enhanced = []
        for u in urls:
            t = _run(fp.skin_enhancer(u, mode="faithful", skin_detail=15))
            r = _run(fp.poll_task(t, kind="enhance", max_wait_s=180))
            enhanced.append(r.get("generated", [u])[0] if isinstance(r.get("generated"), list) else (r.get("generated") or u))

        _update_generation(generation_id, status="completed",
                          image_urls="{" + ",".join(enhanced) + "}",
                          completed_at="now()")
        return {"status": "completed", "urls": enhanced}
    except Exception as e:
        _update_generation(generation_id, status="failed", error_message=str(e)[:1000])
        raise self.retry(exc=e, countdown=10, max_retries=1)


@celery_app.task(name="refine.scene_swap")
def scene_swap_task(*, generation_id: str, persona_ref: str, scene_prompt: str) -> dict:
    """Scene swap = nano-banana com persona ref + prompt do novo cenário."""
    return generate_image_task(
        generation_id=generation_id,
        prompt=scene_prompt,
        persona_ref_url=persona_ref,
        num_variations=1,
        enhance_skin=True,
    )


@celery_app.task(name="refine.cloth_swap")
def cloth_swap_task(*, generation_id: str, person_image: str, outfit_prompt: str) -> dict:
    """Cloth swap via nano-banana edit (mantém pose, troca outfit)."""
    return generate_image_task(
        generation_id=generation_id,
        prompt=f"same person, same pose, change outfit to: {outfit_prompt}. preserve face identity, lighting, background.",
        persona_ref_url=person_image,
        num_variations=1,
        enhance_skin=True,
    )


# ════════════════════════════════════════════════════════════════
#                    BATCH (mass generation)
# ════════════════════════════════════════════════════════════════

@celery_app.task(name="refine.batch_image", bind=True)
def batch_image_task(self, *, batch_id: str, persona_id: str, persona_ref: str,
                     template_ids: list[str], num_per_template: int = 4) -> dict:
    """Gera N imagens × M templates em paralelo via subtasks."""
    from celery import group

    _update_batch(batch_id, status="processing", total_jobs=len(template_ids) * num_per_template)

    # Buscar prompts dos templates
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, prompt FROM templates WHERE id = ANY(:ids)"),
            {"ids": template_ids},
        ).fetchall()
    prompts = {str(r.id): r.prompt for r in rows}

    # Cria generations + dispara subtasks
    generation_ids = []
    subtasks = []
    with engine.begin() as conn:
        for tpl_id in template_ids:
            for _ in range(num_per_template):
                gen_row = conn.execute(text("""
                    INSERT INTO generations (user_id, persona_id, template_id, status, prompt, num_variations)
                    SELECT user_id, :pid, :tid, 'queued', :prompt, 1 FROM personas WHERE id = :pid
                    RETURNING id
                """), {"pid": persona_id, "tid": tpl_id, "prompt": prompts.get(tpl_id, "")}).first()
                gid = str(gen_row.id)
                generation_ids.append(gid)
                subtasks.append(generate_image_task.s(
                    generation_id=gid,
                    prompt=prompts.get(tpl_id, ""),
                    persona_ref_url=persona_ref,
                    num_variations=1,
                ))

    _update_batch(batch_id, generation_ids="{" + ",".join(generation_ids) + "}")
    job = group(subtasks).apply_async()
    return {"batch_id": batch_id, "subtask_group": job.id, "total": len(subtasks)}


@celery_app.task(name="refine.batch_video", bind=True)
def batch_video_task(self, *, batch_id: str, image_urls: list[str], prompt: str, engine: str = "kling_v3") -> dict:
    """N image-to-video em paralelo."""
    from celery import group

    _update_batch(batch_id, status="processing", total_jobs=len(image_urls))
    subtasks = []
    generation_ids = []

    with engine.begin() as conn:
        for img_url in image_urls:
            row = conn.execute(text("""
                INSERT INTO generations (user_id, status, prompt, media_type)
                SELECT user_id, 'queued', :prompt, 'video' FROM batch_jobs WHERE id = :bid
                RETURNING id
            """), {"prompt": prompt, "bid": batch_id}).first()
            gid = str(row.id)
            generation_ids.append(gid)
            subtasks.append(generate_video_task.s(
                generation_id=gid, image_url=img_url, prompt=prompt, engine=engine,
            ))

    _update_batch(batch_id, generation_ids="{" + ",".join(generation_ids) + "}")
    job = group(subtasks).apply_async()
    return {"batch_id": batch_id, "subtask_group": job.id}


# ════════════════════════════════════════════════════════════════
#                    DRIVE IMPORT + STYLE LEARNING + RECREATE
# ════════════════════════════════════════════════════════════════

@celery_app.task(name="refine.drive_import", bind=True)
def drive_import_task(self, *, drive_import_id: str, folder_url: str, user_id: str) -> dict:
    """Baixa todos arquivos da pasta Drive → storage Supabase."""
    from .drive import import_drive_folder

    with engine.begin() as conn:
        conn.execute(text("UPDATE drive_imports SET status = 'importing' WHERE id = :id"),
                     {"id": drive_import_id})

    try:
        result = _run(import_drive_folder(folder_url=folder_url, user_id=user_id, import_id=drive_import_id))
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE drive_imports SET
                  status='ready', total_files=:tot, imported_files=:imp,
                  storage_paths=:paths, completed_at=now()
                WHERE id=:id
            """), {
                "tot": result["total"], "imp": result["imported"],
                "paths": "{" + ",".join(result["paths"]) + "}",
                "id": drive_import_id,
            })
        return result
    except Exception as e:
        with engine.begin() as conn:
            conn.execute(text("UPDATE drive_imports SET status='failed' WHERE id=:id"),
                         {"id": drive_import_id})
        raise


@celery_app.task(name="refine.style_learn", bind=True)
def style_learn_task(self, *, learned_style_id: str, image_paths: list[str],
                       user_description: str, user_id: str) -> dict:
    """
    Style learning manual: user descreve em texto o que quer reproduzir + lista
    imagens de referência. Sistema monta prompt_template usando as primeiras
    imagens como reference_images pro nano-banana-pro.
    """
    with engine.begin() as conn:
        # Monta prompt template com a descrição do user (nano-banana-pro aceita refs)
        tpl = (user_description or "reproduce this style").strip()
        summary = (
            '{"description": "' + tpl.replace('"', '\\"') +
            '", "reference_count": ' + str(len(image_paths)) +
            ', "method": "manual + multi-reference"}'
        )
        conn.execute(text("""
            UPDATE learned_styles SET
              status='ready', style_summary=:summary::jsonb,
              prompt_template=:tpl, example_count=:n,
              example_paths=:paths
            WHERE id=:id
        """), {
            "summary": summary, "tpl": tpl, "n": len(image_paths),
            "paths": "{" + ",".join(image_paths) + "}",
            "id": learned_style_id,
        })
    return {"learned_style_id": learned_style_id, "ready": True}


@celery_app.task(name="refine.calendar_generate", bind=True)
def calendar_generate_task(self, *, calendar_id: str, persona_ref: str | None,
                            prompts: list[dict], enhance_skin: bool = True,
                            upscale: bool = False):
    """Gera todas as imagens de um content_calendar em paralelo via subtasks."""
    from celery import group
    import json

    with engine.begin() as conn:
        conn.execute(text("UPDATE content_calendars SET status='processing' WHERE id=:id"),
                     {"id": calendar_id})

        # Cria 1 generation por post + dispara subtask
        generation_ids = []
        subtasks = []
        updated_posts = []
        for p in prompts:
            row = conn.execute(text("""
                INSERT INTO generations (user_id, persona_id, status, prompt, num_variations, credits_used)
                SELECT user_id, persona_id, 'queued', :prompt, 1, 8
                FROM content_calendars WHERE id = :cid
                RETURNING id
            """), {"prompt": p["prompt"], "cid": calendar_id}).first()
            gid = str(row.id)
            generation_ids.append(gid)
            updated_posts.append({**p, "generation_id": gid})
            subtasks.append(generate_image_task.s(
                generation_id=gid,
                prompt=p["prompt"],
                persona_ref_url=persona_ref,
                num_variations=1,
                enhance_skin=enhance_skin,
                upscale=upscale,
            ))

        conn.execute(text("""
            UPDATE content_calendars SET
              generation_ids = :ids,
              posts = :posts::jsonb
            WHERE id = :id
        """), {
            "ids": "{" + ",".join(generation_ids) + "}",
            "posts": json.dumps(updated_posts),
            "id": calendar_id,
        })

    # Dispatch as subtasks
    job = group(subtasks).apply_async()

    return {
        "calendar_id": calendar_id,
        "subtask_group": str(job.id),
        "total_posts": len(prompts),
    }


@celery_app.task(name="refine.regen_previews", bind=True)
def regen_previews_task(self, *, target: str = "all", limit: int | None = None):
    """
    Regenera previews de todos templates/presets/worlds via Freepik nano-banana 2K.
    Roda dentro do worker da VPS (acesso DB + Supabase + Freepik OK).
    """
    import os, httpx
    from supabase import create_client
    from .freepik import FreepikClient

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    fp = FreepikClient(api_keys=[k.strip() for k in os.environ["FREEPIK_API_KEYS"].split(",") if k.strip()])

    async def _gen_one(prompt: str, ratio: str = "portrait_4_5") -> str | None:
        full = f"{prompt}, editorial photography, 4K quality, professional lighting"
        try:
            tid = await fp.nano_banana_pro(prompt=full, aspect_ratio=ratio, size="2k")
            r = await fp.poll_task(tid, kind="image", max_wait_s=300)
            urls = r.get("generated") or r.get("urls") or []
            if isinstance(urls, str): return urls
            return urls[0] if urls else None
        except Exception:
            return None

    async def _process(table: str, id_col: str, id_val: str, prompt: str, ratio: str, update_col: str):
        gen_url = await _gen_one(prompt, ratio)
        if not gen_url: return False
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                img = (await c.get(gen_url)).content
            path = f"{table}/{id_val}.jpg"
            sb.storage.from_("previews").upload(path, img,
                file_options={"content-type": "image/jpeg", "upsert": "true"})
            pub_url = sb.storage.from_("previews").get_public_url(path)
            with engine.begin() as conn:
                conn.execute(text(f"UPDATE {table} SET {update_col} = :u WHERE {id_col} = :id"),
                             {"u": pub_url, "id": id_val})
            return True
        except Exception:
            return False

    async def _run():
        results: dict = {}

        if target in ("templates", "all"):
            with engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT id, name, prompt, media_type FROM templates
                    WHERE is_public=true AND (preview_url IS NULL OR preview_url LIKE '/placeholder%')
                    ORDER BY uses_count DESC NULLS LAST
                    LIMIT :l
                """), {"l": limit or 1000}).fetchall()
            ok = 0
            for r in rows:
                ratio = "social_story_9_16" if r.media_type == "video" else "portrait_4_5"
                if await _process("templates", "id", str(r.id), r.prompt or r.name, ratio, "preview_url"):
                    ok += 1
            results["templates"] = f"{ok}/{len(rows)}"

        if target in ("presets", "all"):
            with engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT id, name, base_prompt FROM model_presets
                    WHERE reference_image_url LIKE '/presets%'
                    LIMIT :l
                """), {"l": limit or 100}).fetchall()
            ok = 0
            for r in rows:
                if await _process("model_presets", "id", str(r.id),
                                   f"{r.base_prompt}, full body editorial portrait", "portrait_4_5",
                                   "reference_image_url"):
                    ok += 1
            results["presets"] = f"{ok}/{len(rows)}"

        if target in ("worlds", "all"):
            with engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT id, name, prompt_template FROM worlds
                    WHERE is_public=true AND preview_url IS NULL
                    LIMIT :l
                """), {"l": limit or 100}).fetchall()
            ok = 0
            for r in rows:
                if await _process("worlds", "id", str(r.id), r.prompt_template, "widescreen_16_9", "preview_url"):
                    ok += 1
            results["worlds"] = f"{ok}/{len(rows)}"

        await fp.close()
        return results

    return _run_async_in_worker(_run())


def _run_async_in_worker(coro):
    """Helper pra rodar coroutine no worker síncrono Celery."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="refine.recreate", bind=True)
def recreate_task(self, *, recreate_job_id: str, persona_id: str, persona_ref: str,
                  drive_import_id: str, options: dict | None = None) -> dict:
    """Recria cada foto da pasta Drive usando a persona do user."""
    options = options or {}
    from celery import group

    with engine.begin() as conn:
        paths_row = conn.execute(text(
            "SELECT storage_paths FROM drive_imports WHERE id=:id"
        ), {"id": drive_import_id}).first()
        paths = list(paths_row.storage_paths) if paths_row else []

        conn.execute(text("UPDATE recreate_jobs SET status='processing', total_files=:t WHERE id=:id"),
                     {"t": len(paths), "id": recreate_job_id})

    subtasks = []
    generation_ids = []
    with engine.begin() as conn:
        for src_path in paths:
            row = conn.execute(text("""
                INSERT INTO generations (user_id, persona_id, recreate_job_id, source_image_path, status, prompt, num_variations)
                SELECT user_id, :pid, :rid, :src, 'queued', 'recreate this photo using my persona', 1
                FROM personas WHERE id = :pid
                RETURNING id
            """), {"pid": persona_id, "rid": recreate_job_id, "src": src_path}).first()
            gid = str(row.id)
            generation_ids.append(gid)
            subtasks.append(generate_image_task.s(
                generation_id=gid,
                prompt=f"recreate this exact photo composition, lighting and mood, but with my model. Source: {src_path}",
                persona_ref_url=persona_ref,
                num_variations=1,
                enhance_skin=options.get("skin_enhance", True),
                upscale=options.get("magnific", False),
            ))

    with engine.begin() as conn:
        conn.execute(text("UPDATE recreate_jobs SET generation_ids=:ids WHERE id=:rid"),
                     {"ids": "{" + ",".join(generation_ids) + "}", "rid": recreate_job_id})

    job = group(subtasks).apply_async()
    return {"recreate_job_id": recreate_job_id, "total": len(subtasks)}


# ════════════════════════════════════════════════════════════════
#                    BILLING / SUBSCRIPTION TASKS
# ════════════════════════════════════════════════════════════════
# Reposição de créditos é feita automaticamente pelo Stripe webhook
# (invoice.paid) tanto pra mensais quanto anuais — não precisa de cron.

@celery_app.task(name="refine.cleanup_daily_usage")
def cleanup_daily_usage():
    """Remove registros de daily_usage com mais de 7 dias (não precisa pra cap)."""
    with engine.begin() as conn:
        result = conn.execute(text(
            "DELETE FROM daily_usage WHERE used_at < NOW() - INTERVAL '7 days'"
        ))
    return {"deleted_rows": getattr(result, "rowcount", 0)}

