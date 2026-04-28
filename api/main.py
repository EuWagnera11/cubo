"""
Refine — Backend FastAPI

Plataforma completa de IA influencer:
  Image:  text-to-image, face/scene/cloth swap, upscale, skin enhance, relight
  Video:  image-to-video (Kling, Hailuo, Runway), batch, motion control
  Drive:  import folders, style learning (Claude Opus 4.7), recreate jobs
  Batch:  mass image/video generation com workers Celery

Endpoints:
  /generations        — image/video gen
  /swaps              — face / scene / cloth
  /batch              — mass generation
  /drive              — drive imports + learn + recreate
  /enhance            — upscale, skin, bg remove, relight
  /personas           — CRUD persona
  /templates          — list templates
  /billing            — Stripe checkout/webhook
  /uploads            — signed URLs Supabase
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


class Settings:
    APP_NAME = "Refine API"
    VERSION = "1.0.0"
    FREEPIK_API_KEYS = [k.strip() for k in os.environ.get("FREEPIK_API_KEYS", "").split(",") if k.strip()]
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    REDIS_URL = os.environ.get("REDIS_URL", "")
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    CORS_ORIGINS = [
        o.strip() for o in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:3000,https://app.refinecubo.com.br,https://refinecubo.com.br,https://soph.ia.com.br"
        ).split(",") if o.strip()
    ]


settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"🚀 {settings.APP_NAME} v{settings.VERSION} starting...")
    warnings = []
    if not settings.FREEPIK_API_KEYS:
        warnings.append("FREEPIK_API_KEYS not set — generation will fail")
    if not settings.DATABASE_URL:
        warnings.append("DATABASE_URL not set")
    if not settings.REDIS_URL:
        warnings.append("REDIS_URL not set — Celery workers won't dispatch")
    for w in warnings:
        print(f"⚠️  {w}")
    yield
    print("🛑 Shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Refine — AI influencer studio backend",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────── Request timing middleware ───────────────

@app.middleware("http")
async def add_timing(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{(time.time() - start)*1000:.1f}ms"
    return response


# ─────────────── Health & root ───────────────

@app.get("/")
def root():
    return {"app": settings.APP_NAME, "version": settings.VERSION, "docs": "/docs"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": settings.VERSION,
        "freepik_keys": len(settings.FREEPIK_API_KEYS),
        "db": bool(settings.DATABASE_URL),
        "redis": bool(settings.REDIS_URL),
    }


# ─────────────── Routers ───────────────

# Carrega routers só se DATABASE_URL existe (pra não quebrar /docs sem DB)
if settings.DATABASE_URL:
    from .routers import generations as r_gen
    from .routers import swaps as r_swaps
    from .routers import batch as r_batch
    from .routers import drive_router as r_drive
    from .routers import enhance as r_enhance
    from .routers import personas as r_personas
    from .routers import billing as r_billing
    from .routers import uploads as r_uploads
    from .routers import audio as r_audio
    from .routers import edit as r_edit
    from .routers import specialized as r_spec
    from .routers import catalog as r_catalog
    from .routers import admin as r_admin
    from .routers import calendar as r_calendar

    # Core
    app.include_router(r_gen.router)
    app.include_router(r_personas.router)
    app.include_router(r_personas.templates_router)

    # Workflows
    app.include_router(r_swaps.router)
    app.include_router(r_batch.router)
    app.include_router(r_calendar.router)
    app.include_router(r_drive.router)
    app.include_router(r_enhance.router)
    app.include_router(r_edit.router)
    app.include_router(r_spec.router)

    # AI audio
    app.include_router(r_audio.router)

    # Catalog
    app.include_router(r_catalog.worlds_router)
    app.include_router(r_catalog.presets_router)
    app.include_router(r_catalog.music_router)

    # Billing & uploads
    app.include_router(r_billing.router)
    app.include_router(r_uploads.router)

    # Admin
    app.include_router(r_admin.router)


# ─────────────── Error handler ───────────────

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Captura erros não tratados e retorna JSON limpo (sem stack trace na resposta)."""
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": str(exc)[:200]},
    )
