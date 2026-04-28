"""
Cubo Studio — Backend FastAPI
Pipeline de IA influencer (nano-banana + skin enhancers + Magnific) exposto como API REST.

Setup local:
    pip install -r requirements.txt
    uvicorn api.main:app --reload

Deploy (Railway/Fly.io/Render):
    Dockerfile incluído em api/Dockerfile

Documentação automática:
    /docs (Swagger UI)
    /redoc (ReDoc)
    /openapi.json (importar no Lovable pra gerar tipos)
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, EmailStr

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

class Settings:
    APP_NAME = "Cubo Studio API"
    VERSION = "1.0.0"
    FREEPIK_API_KEYS = [k.strip() for k in os.environ.get("FREEPIK_API_KEYS", "").split(",") if k.strip()]
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cubo")
    JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRE_MIN = 60 * 24 * 7   # 7 dias
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STORAGE_BUCKET = os.environ.get("STORAGE_BUCKET", "cubo-generations")
    CORS_ORIGINS = [
        "http://localhost:3000",
        "https://app.refinecubo.com.br",
        "https://refinecubo.com.br",
        "https://soph.ia.com.br",
    ]

settings = Settings()

# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: conectar DB, cache, queue, etc
    print(f"🚀 {settings.APP_NAME} v{settings.VERSION} starting...")
    if not settings.FREEPIK_API_KEYS:
        print("⚠️  WARNING: FREEPIK_API_KEYS not set — generation will fail")
    yield
    # Shutdown: cleanup
    print("🛑 Shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Pipeline IA influencer (nano-banana + enhancers + Magnific)",
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

security = HTTPBearer()


# ─────────────────────────────────────────────────────────────────────────────
# AUTH (JWT) — placeholder, integrar com Supabase Auth ou Clerk em produção
# ─────────────────────────────────────────────────────────────────────────────

def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Decoded JWT payload. Trocar por Supabase JWT verify em produção."""
    # TODO: substituir por jwt.decode com verificação real
    token = creds.credentials
    if not token or token == "invalid":
        raise HTTPException(401, "Invalid or expired token")
    # Mock: retorna user fake
    return {"user_id": "usr_demo", "email": "demo@cubo.ag", "tier": "pro", "credits": 247}


CurrentUser = Depends(verify_token)


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMAS (Pydantic)
# ─────────────────────────────────────────────────────────────────────────────

# Auth
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=2, max_length=100)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class AuthResponse(BaseModel):
    user: dict
    token: str

# Personas
class PersonaCreateMetadata(BaseModel):
    age: Optional[int] = None
    city: Optional[str] = None
    ethnicity: Optional[str] = None
    hair_color: Optional[str] = None
    style_tag: Optional[str] = None
    restrictions: list[str] = Field(default_factory=list)

class PersonaCreate(BaseModel):
    name: str
    metadata: PersonaCreateMetadata = Field(default_factory=PersonaCreateMetadata)

class Persona(BaseModel):
    id: str
    name: str
    ref_image_url: str
    canonical_grid_url: Optional[str] = None
    status: Literal["pending_grid", "ready", "failed"]
    metadata: PersonaCreateMetadata
    created_at: str

# Generations
AspectRatio = Literal["1:1", "3:4", "9:16", "4:5", "4:3", "16:9", "2:3", "3:2"]
Resolution = Literal["1K", "2K", "4K"]
SkinEnhanceMode = Literal["faithful", "flexible", "none"]

class GenerationOptions(BaseModel):
    magnific_upscale: bool = False
    skin_enhance: SkinEnhanceMode = "faithful"
    preserve_logos: bool = True
    negative_prompt: str = "no tattoos, eyes properly aligned no strabismus"

class GenerationCreate(BaseModel):
    persona_id: str
    template_id: Optional[str] = None
    prompt: Optional[str] = None
    aspect_ratio: AspectRatio = "3:4"
    resolution: Resolution = "4K"
    num_variations: int = Field(1, ge=1, le=6)
    options: GenerationOptions = Field(default_factory=GenerationOptions)

class GenerationResult(BaseModel):
    id: str
    url: str
    thumbnail_url: str
    dimensions: tuple[int, int]
    size_bytes: int
    metadata: dict

class Generation(BaseModel):
    id: str
    status: Literal["queued", "processing", "enhancing", "upscaling", "completed", "failed"]
    stage: Optional[str] = None
    progress: float = 0.0
    persona_id: str
    template_id: Optional[str] = None
    prompt_used: Optional[str] = None
    config: dict
    results: list[GenerationResult] = Field(default_factory=list)
    error: Optional[str] = None
    credits_charged: int
    created_at: str
    completed_at: Optional[str] = None

# Templates
class Template(BaseModel):
    id: str
    name: str
    category: str
    subcategory: Optional[str] = None
    preview_url: str
    description: str
    popularity: int = 0
    rating: float = 5.0
    default_config: dict
    tags: list[str]
    complexity: Literal["easy", "medium", "hard", "very-hard"]
    credits_cost: int
    is_premium: bool = False

# Billing
class BillingBalance(BaseModel):
    credits: int
    tier: Literal["free", "starter", "pro", "agency", "enterprise"]
    tier_credits_monthly: int
    renewal_date: Optional[str] = None
    extra_credits_purchased: int = 0

class CheckoutRequest(BaseModel):
    tier: Optional[Literal["starter", "pro", "agency"]] = None
    credits_pack: Optional[int] = None
    success_url: str
    cancel_url: str

class CheckoutResponse(BaseModel):
    checkout_url: str

# Generic
class JobStatus(BaseModel):
    id: str
    type: str
    status: Literal["queued", "processing", "completed", "failed"]
    stage: Optional[str] = None
    progress: float = 0.0
    result_id: Optional[str] = None
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH / ROOT
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"service": settings.APP_NAME, "version": settings.VERSION, "docs": "/docs"}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "version": settings.VERSION,
        "freepik_keys_configured": len(settings.FREEPIK_API_KEYS),
        "timestamp": time.time(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/auth/signup", response_model=AuthResponse, status_code=201)
async def signup(req: SignupRequest):
    """Criar conta. Retorna user + JWT token."""
    # TODO: hash password, persist DB, send welcome email
    user = {
        "id": f"usr_{uuid4().hex[:8]}",
        "email": req.email,
        "name": req.name,
        "tier": "free",
        "credits": 3,
    }
    token = "mock_jwt_" + uuid4().hex
    return AuthResponse(user=user, token=token)


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    """Login com email/password."""
    # TODO: verify password against DB
    user = {"id": "usr_demo", "email": req.email, "tier": "pro", "credits": 247}
    token = "mock_jwt_" + uuid4().hex
    return AuthResponse(user=user, token=token)


@app.get("/api/auth/me")
async def me(user: dict = CurrentUser):
    return user


# ─────────────────────────────────────────────────────────────────────────────
# PERSONAS
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/personas", response_model=Persona, status_code=201)
async def create_persona(req: PersonaCreate, user: dict = CurrentUser):
    """Cria nova persona. Upload da imagem via /api/uploads/persona-photo separado."""
    # TODO: validate tier limit (Free=0, Starter=1, Pro=3, Agency=15)
    persona = Persona(
        id=f"per_{uuid4().hex[:8]}",
        name=req.name,
        ref_image_url="https://r2.cubo/placeholder.png",
        status="pending_grid",
        metadata=req.metadata,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return persona


@app.get("/api/personas", response_model=list[Persona])
async def list_personas(user: dict = CurrentUser):
    """Lista personas do user."""
    return []


@app.get("/api/personas/{persona_id}", response_model=Persona)
async def get_persona(persona_id: str, user: dict = CurrentUser):
    raise HTTPException(404, f"Persona {persona_id} not found")


@app.post("/api/personas/{persona_id}/generate-grid", response_model=JobStatus, status_code=202)
async def generate_persona_grid(persona_id: str, bg: BackgroundTasks, user: dict = CurrentUser):
    """Gera o grid 4 ângulos canônico (Sophia-style). Async."""
    job_id = f"job_{uuid4().hex[:8]}"
    # bg.add_task(run_grid_generation, persona_id, user["user_id"])
    return JobStatus(
        id=job_id,
        type="persona_grid_generation",
        status="queued",
    )


@app.delete("/api/personas/{persona_id}", status_code=204)
async def delete_persona(persona_id: str, user: dict = CurrentUser):
    return


# ─────────────────────────────────────────────────────────────────────────────
# GENERATIONS (core)
# ─────────────────────────────────────────────────────────────────────────────

def calc_credits(req: GenerationCreate) -> int:
    """Cálculo de créditos (referência saas_api_spec.md §11)."""
    base = 8  # nano-banana 4K
    if req.options.skin_enhance != "none":
        base += 2  # 2 enhancers (lighting + skin)
    if req.options.magnific_upscale:
        base += 5
    if req.options.preserve_logos:
        base += 1  # compose_protect
    return base * req.num_variations


@app.post("/api/generations", response_model=Generation, status_code=202)
async def create_generation(
    req: GenerationCreate,
    bg: BackgroundTasks,
    user: dict = CurrentUser,
):
    """Cria job de geração. Cobra créditos. Enfileira pipeline."""
    cost = calc_credits(req)

    # TODO: validate user has credits
    if user.get("credits", 0) < cost:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "INSUFFICIENT_CREDITS",
                "message": f"Você tem {user.get('credits', 0)} créditos. Esta geração custa {cost}.",
                "details": {"balance": user.get("credits", 0), "needed": cost},
            },
        )

    gen_id = f"gen_{uuid4().hex[:8]}"
    gen = Generation(
        id=gen_id,
        status="queued",
        persona_id=req.persona_id,
        template_id=req.template_id,
        config=req.model_dump(),
        credits_charged=cost,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    # Enqueue pipeline
    # bg.add_task(run_generation_pipeline, gen_id, req, user["user_id"])

    return gen


@app.get("/api/generations/{gen_id}", response_model=Generation)
async def get_generation(gen_id: str, user: dict = CurrentUser):
    """Status + results de uma geração."""
    # TODO: fetch from DB
    raise HTTPException(404, f"Generation {gen_id} not found")


@app.get("/api/generations", response_model=list[Generation])
async def list_generations(
    user: dict = CurrentUser,
    persona_id: Optional[str] = None,
    template_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    """Lista gerações do user com filtros."""
    return []


@app.delete("/api/generations/{gen_id}", status_code=204)
async def delete_generation(gen_id: str, user: dict = CurrentUser):
    return


@app.post("/api/generations/{gen_id}/regenerate", response_model=Generation, status_code=202)
async def regenerate(gen_id: str, user: dict = CurrentUser):
    """Regenera com novo seed. Cobra novamente."""
    raise HTTPException(404, f"Generation {gen_id} not found")


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/templates", response_model=list[Template])
async def list_templates(category: Optional[str] = None, search: Optional[str] = None):
    """Lista templates. Carrega do JSON gerado pela clusterização (content_clusters.md)."""
    # TODO: load from db (seeded from content_clusters.json)
    return []


@app.get("/api/templates/{tpl_id}", response_model=Template)
async def get_template(tpl_id: str):
    raise HTTPException(404, f"Template {tpl_id} not found")


# ─────────────────────────────────────────────────────────────────────────────
# BILLING
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/billing/balance", response_model=BillingBalance)
async def billing_balance(user: dict = CurrentUser):
    return BillingBalance(
        credits=user.get("credits", 0),
        tier=user.get("tier", "free"),
        tier_credits_monthly={"free": 3, "starter": 50, "pro": 300, "agency": 1500}.get(user.get("tier", "free"), 0),
    )


@app.post("/api/billing/checkout", response_model=CheckoutResponse)
async def billing_checkout(req: CheckoutRequest, user: dict = CurrentUser):
    """Cria sessão Stripe checkout."""
    # TODO: stripe.checkout.Session.create(...)
    return CheckoutResponse(checkout_url="https://checkout.stripe.com/mock-session")


@app.post("/api/billing/portal")
async def billing_portal(user: dict = CurrentUser):
    """Stripe Customer Portal URL."""
    return {"portal_url": "https://billing.stripe.com/p/mock"}


@app.get("/api/billing/history")
async def billing_history(user: dict = CurrentUser, page: int = 1, limit: int = 20):
    return {"data": [], "pagination": {"page": page, "limit": limit, "total": 0, "pages": 0}}


@app.post("/api/billing/webhook")
async def stripe_webhook(payload: dict):
    """Handler pra webhooks Stripe (subscription updates, payment success/fail)."""
    # TODO: verify signature, process event
    return {"received": True}


# ─────────────────────────────────────────────────────────────────────────────
# UPLOADS
# ─────────────────────────────────────────────────────────────────────────────

class UploadRequest(BaseModel):
    filename: str
    content_type: str

class UploadResponse(BaseModel):
    upload_url: str
    file_id: str
    expires_at: str

@app.post("/api/uploads/persona-photo", response_model=UploadResponse)
async def upload_persona_photo(req: UploadRequest, user: dict = CurrentUser):
    """Retorna signed PUT URL pra upload direto S3/R2."""
    # TODO: gerar signed URL real (boto3)
    file_id = f"f_{uuid4().hex[:8]}"
    return UploadResponse(
        upload_url=f"https://r2.cubo.ag/uploads/{file_id}?signature=mock",
        file_id=file_id,
        expires_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# JOBS (generic async tracking)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str, user: dict = CurrentUser):
    raise HTTPException(404, f"Job {job_id} not found")


# ─────────────────────────────────────────────────────────────────────────────
# DEBUG (dev only)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/debug/freepik-test", include_in_schema=False)
async def debug_freepik():
    """Verifica conexão com Freepik."""
    if not settings.FREEPIK_API_KEYS:
        return {"ok": False, "error": "No FREEPIK_API_KEYS configured"}
    return {"ok": True, "keys_configured": len(settings.FREEPIK_API_KEYS)}


# ─────────────────────────────────────────────────────────────────────────────
# WORKER PIPELINE (placeholder — moverá pra api/jobs/worker.py)
# ─────────────────────────────────────────────────────────────────────────────

async def run_generation_pipeline(gen_id: str, req: GenerationCreate, user_id: str):
    """
    Executar em worker (Inngest/Celery), não no request.
    Etapas:
      1. Build prompt (template + persona)
      2. nano-banana-pro 4K
      3. safe_skin_enhance lighting
      4. safe_skin_enhance faithful skin
      5. (optional) Magnific upscale
      6. (optional) compose_protect
      7. Upload final to storage
      8. Update generation record
    """
    pass  # implementar em api/jobs/worker.py importando os scripts existentes


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
