# Cubo Studio — Backend API

FastAPI backend que orquestra o pipeline de IA influencer da Cubo:
nano-banana-pro 4K → safe_skin_enhance → Magnific Sparkle → compose_protect.

## Quick start (local)

```bash
cd api
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # edita com suas keys
uvicorn api.main:app --reload
```

Acesse:
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json (importar no Lovable)

## Deploy

### Railway
```bash
railway login
railway init
railway up
# adicionar env vars no dashboard Railway
```

### Fly.io
```bash
fly launch
fly secrets set FREEPIK_API_KEYS=...
fly deploy
```

### Render
Criar Web Service → conectar GitHub → branch `main` → build with Dockerfile.

## Estrutura

```
api/
├── main.py              # FastAPI app + endpoints (1 arquivo no MVP)
├── requirements.txt     # deps Python
├── Dockerfile           # container image
├── .env.example
└── README.md            # este arquivo
```

Conforme escala, dividir em módulos:
- `auth/`, `personas/`, `generations/`, `templates/`, `billing/`, `uploads/`, `jobs/`

## Pipeline interno (worker)

Quando user POSTa `/api/generations`, criamos um job que executa:

```
1. Build prompt (template + persona) → string
2. nano-banana-pro 4K → out/raw/<gen_id>_4k.png
3. safe_skin_enhance.py improve_lighting → out/enhanced/<gen_id>_lit.png
4. safe_skin_enhance.py faithful skin_detail=20 → out/enhanced/<gen_id>_skin.png
5. (opcional) upscale.py Magnific 2x → out/enhanced/<gen_id>_magnific.png
6. (opcional) compose_protect.py → out/finals/<gen_id>.png
7. Upload R2/S3
8. Update DB record (status=completed, results=[...])
```

Os scripts já existem em `nano-banana-swap-v2/`:
- `gen_scene.py` — orchestra Freepik nano-banana
- `safe_skin_enhance.py` — enhancers com proteção de logos
- `upscale.py` — Magnific Sparkle
- `compose_protect.py` — composição final

Worker importa essas funções e expõe via job queue (Inngest preferred).

## Auth

MVP usa JWT mock. Em produção:

**Opção A — Supabase Auth** (recomendado pra início)
```python
from supabase import create_client
supabase = create_client(url, anon_key)
# Verifica JWT via supabase.auth.get_user(token)
```

**Opção B — Clerk**
```python
from clerk_sdk import Clerk
clerk = Clerk(secret_key=...)
# Verifica session via clerk.sessions.verify_session(...)
```

## Observability

- Sentry SDK pra errors (instalado em deps)
- Logs estruturados (JSON) em produção
- Métricas Prometheus opcional (`/metrics`)

## Rate limits

Implementar via slowapi:
```python
from slowapi import Limiter
limiter = Limiter(key_func=lambda: user["user_id"])

@app.post("/api/generations")
@limiter.limit("30/minute")
async def create_generation(...): ...
```

## Testes

```bash
pytest api/tests/
```

## Próximos passos

- [ ] Conectar Supabase Postgres real
- [ ] Implementar SQLAlchemy models
- [ ] Worker Inngest (substituir BackgroundTasks)
- [ ] Stripe webhooks completos
- [ ] WebSocket pra progress real-time
- [ ] Boto3/aioboto3 pra R2 uploads
- [ ] Carregar templates do `content_clusters.json` (após clusterização)
