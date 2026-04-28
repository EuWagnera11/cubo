# SaaS Cubo — API Specification (FastAPI Backend)

**Versão:** 1.0
**Base URL prod:** `https://api.refinecubo.com.br`
**Base URL dev:** `http://localhost:8000`
**Auth:** JWT Bearer token in `Authorization` header

---

## 1. Conventions

- All requests/responses: JSON
- Datetimes: ISO 8601 UTC (`2026-04-27T18:30:00Z`)
- Pagination: `?page=1&limit=20`
- Errors: standardized format

```json
{
  "error": {
    "code": "INSUFFICIENT_CREDITS",
    "message": "Você tem 5 créditos. Esta geração custa 12.",
    "details": { "balance": 5, "needed": 12 }
  }
}
```

---

## 2. Auth Endpoints

### `POST /api/auth/signup`
```json
// REQUEST
{
  "email": "user@example.com",
  "password": "secret123",
  "name": "Daniel Silva"
}

// RESPONSE 201
{
  "user": { "id": "usr_abc", "email": "...", "name": "...", "tier": "free", "credits": 3 },
  "token": "eyJhbGc..."
}
```

### `POST /api/auth/login`
```json
// REQUEST
{ "email": "...", "password": "..." }

// RESPONSE 200
{ "user": {...}, "token": "..." }
```

### `POST /api/auth/google`
OAuth callback. Returns same shape as login.

### `POST /api/auth/refresh`
```json
// HEADER: Authorization: Bearer <expired_or_valid_token>
// RESPONSE: { "token": "new_jwt..." }
```

### `GET /api/auth/me`
Returns authenticated user.

---

## 3. Personas Endpoints

### `POST /api/personas`
```json
// REQUEST (multipart/form-data)
{
  "name": "Sophia",
  "ref_image": <file>,            // 1ª foto-base
  "additional_images": [<file>],   // opcional, até 4
  "metadata": {
    "age": 23,
    "city": "São Paulo",
    "ethnicity": "white",
    "hair_color": "ginger copper",
    "style_tag": "brazilian_adult_sensual",
    "restrictions": ["no_tattoos"]
  }
}

// RESPONSE 201
{
  "id": "per_abc123",
  "name": "Sophia",
  "ref_image_url": "https://r2.cubo/...",
  "canonical_grid_url": null,    // será gerado depois
  "status": "pending_grid",       // pending_grid → ready
  "created_at": "..."
}
```

### `POST /api/personas/:id/generate-grid`
Gera o grid 4 ângulos canônico (Sophia-style). Async job.

```json
// RESPONSE 202
{
  "job_id": "job_xyz",
  "status": "processing",
  "eta_seconds": 180
}
```

Frontend polls `/api/jobs/:job_id` ou WS `/ws/jobs/:job_id` até completar.

### `GET /api/personas`
Lista personas do user. Tier limita quantidade.

### `GET /api/personas/:id`
Retorna persona + recent generations.

### `PATCH /api/personas/:id`
Atualiza metadata.

### `DELETE /api/personas/:id`
Deleta persona (não pode estar em uso).

---

## 4. Generations Endpoints

### `POST /api/generations`
```json
// REQUEST
{
  "persona_id": "per_abc",
  "template_id": "tpl_starbucks_selfie",  // opcional
  "prompt": "...",                         // opcional override
  "aspect_ratio": "3:4",                   // 1:1 | 3:4 | 9:16 | 4:5 | 4:3 | 16:9
  "resolution": "4K",                      // 1K | 2K | 4K
  "num_variations": 4,
  "options": {
    "magnific_upscale": false,    // pro tier
    "skin_enhance": "faithful",   // faithful | flexible | none
    "preserve_logos": true,        // safe_skin_enhance edge-based
    "negative_prompt": "no tattoos, eyes properly aligned"
  }
}

// RESPONSE 202
{
  "id": "gen_xyz",
  "status": "queued",
  "credits_charged": 12,
  "estimated_seconds": 240,
  "created_at": "..."
}
```

### `GET /api/generations/:id`
```json
// RESPONSE 200
{
  "id": "gen_xyz",
  "status": "completed",  // queued | processing | enhancing | upscaling | completed | failed
  "stage": "enhancement", // optional, current step
  "progress": 0.75,        // 0.0-1.0
  "persona_id": "per_abc",
  "template_id": "tpl_starbucks_selfie",
  "prompt_used": "Photorealistic in-car selfie...",
  "config": { "aspect_ratio": "3:4", "resolution": "4K", ... },
  "results": [
    {
      "id": "img_001",
      "url": "https://r2.cubo/gen_xyz/var_1.png",
      "thumbnail_url": "https://r2.cubo/gen_xyz/var_1_thumb.png",
      "dimensions": [3584, 4800],
      "size_bytes": 49283749,
      "metadata": { "seed": 42, "stages_applied": ["raw", "lit", "skin", "magnific"] }
    },
    // ... up to num_variations
  ],
  "error": null,
  "created_at": "...",
  "completed_at": "..."
}
```

### `GET /api/generations`
Paginada, com filtros:
- `?persona_id=per_abc`
- `?template_id=tpl_xyz`
- `?status=completed`
- `?from=2026-04-01&to=2026-04-30`

### `DELETE /api/generations/:id`
Deleta geração. Imagens removidas do storage.

### `POST /api/generations/:id/regenerate`
Regenera com novo seed. Cobra novamente.

---

## 5. Templates Endpoints

### `GET /api/templates`
```json
// RESPONSE 200
{
  "data": [
    {
      "id": "tpl_starbucks_selfie",
      "name": "Starbucks In-Car Selfie",
      "category": "lifestyle",
      "subcategory": "café",
      "preview_url": "https://...",
      "description": "Pose 3/4 turn in luxury car, oversized sunglasses, holding venti Starbucks...",
      "popularity": 234,
      "rating": 4.8,
      "default_config": { "aspect_ratio": "3:4", "resolution": "4K" },
      "tags": ["car", "starbucks", "sunglasses", "candid", "easy"],
      "complexity": "easy",
      "credits_cost": 12,
      "is_premium": false
    },
    // ...
  ],
  "pagination": { "page": 1, "limit": 20, "total": 45, "pages": 3 }
}
```

### `GET /api/templates/:id`
Detail with full prompt template + examples.

### `POST /api/templates` (Pro+ tier)
User cria template custom.

```json
// REQUEST
{
  "name": "My Custom Template",
  "category": "fitness",
  "prompt_template": "Sophia in {{location}} wearing {{outfit}}...",
  "default_config": {...},
  "is_public": false  // se true, aparece pra outros (com user attribution)
}
```

### `DELETE /api/templates/:id`
Custom only. Não pode deletar templates oficiais Cubo.

---

## 6. Billing Endpoints

### `GET /api/billing/balance`
```json
{
  "credits": 247,
  "tier": "pro",
  "tier_credits_monthly": 300,
  "renewal_date": "2026-05-15",
  "extra_credits_purchased": 0
}
```

### `GET /api/billing/history`
```json
{
  "data": [
    {
      "id": "inv_xyz",
      "type": "subscription",  // subscription | one_time | refund
      "amount_cents": 9700,
      "currency": "USD",
      "status": "paid",
      "description": "Pro Plan - Mar 2026",
      "stripe_invoice_url": "https://...",
      "created_at": "..."
    }
  ],
  "pagination": {...}
}
```

### `POST /api/billing/checkout`
```json
// REQUEST
{
  "tier": "pro",            // pra subscription
  "credits_pack": null,     // ou pra one-time
  "success_url": "https://app.../billing?success=true",
  "cancel_url": "https://app.../billing?canceled=true"
}

// RESPONSE
{ "checkout_url": "https://checkout.stripe.com/..." }
```

### `POST /api/billing/portal`
Returns Stripe customer portal URL (manage subscription, update card, cancel).

### `GET /api/billing/tier`
Returns current tier + features unlocked.

### `POST /api/billing/webhook` (Stripe webhook)
Handles `checkout.session.completed`, `invoice.payment_succeeded`, `customer.subscription.deleted`, etc.

---

## 7. Uploads Endpoints

### `POST /api/uploads/persona-photo`
Returns S3/R2 signed PUT URL for direct upload.

```json
// REQUEST
{ "filename": "sophia_main.png", "content_type": "image/png" }

// RESPONSE
{
  "upload_url": "https://r2.cubo/...?signature=...",
  "file_id": "f_abc",
  "expires_at": "..."
}
```

Frontend then PUTs file directly to `upload_url`. Backend tracks via `file_id`.

---

## 8. Jobs / Async Endpoints

### `GET /api/jobs/:job_id`
Generic job status (used by grid generation, large batches).

```json
{
  "id": "job_xyz",
  "type": "persona_grid_generation",
  "status": "processing",
  "stage": "calling_freepik",
  "progress": 0.4,
  "result_id": null,    // populated when completed
  "error": null
}
```

### `WebSocket /ws/jobs/:job_id`
Real-time updates. Server pushes:
```json
{ "type": "progress", "data": { "progress": 0.5, "stage": "skin_enhance" } }
{ "type": "completed", "data": { "result_id": "gen_abc" } }
{ "type": "error", "data": { "code": "...", "message": "..." } }
```

---

## 9. Pipeline interno (não exposto na API pública)

Quando user POSTs `/api/generations`, internamente:

```
1. Validate (auth, credits, persona ownership)
2. Charge credits (transactional)
3. Enqueue job → job queue (Inngest / BullMQ)
4. Worker picks up job:
   a. Build prompt from template + user inputs
   b. Call Freepik nano-banana-pro (4K)
   c. Call safe_skin_enhance (improve_lighting)
   d. Call safe_skin_enhance (faithful skin_detail=20)
   e. (optional) Magnific upscale 2x
   f. (optional) compose_protect (preserve logos)
   g. Upload final to R2/Supabase Storage
   h. Update generation record (status=completed, results=[...])
5. Notify user (WS push or email if takes >10min)
```

Cada etapa rastreia tempo + erros pra observability.

---

## 10. Rate limits

```
Free tier:    10 req/min
Starter:      30 req/min
Pro:          120 req/min
Agency:       600 req/min
Enterprise:   custom
```

Endpoints que mais consomem rate: `POST /api/generations`, `POST /api/personas/.../generate-grid`.

---

## 11. Cost calculation (créditos por geração)

```
Base nano-banana 4K:                   = 8 credits
+ skin_enhance lighting (light):       = 1 credit
+ skin_enhance skin (faithful):        = 1 credit
+ Magnific upscale 2x (Pro+):          = 5 credits
+ compose_protect (logos):             = 0.5 credit
+ Each variation:                      = base × N

Examples:
  4K + 2 enhancers + 1 var:            = 10 credits
  4K + 2 enhancers + Magnific + 4 var: = 60 credits
  Persona grid generation (4 angles):  = 32 credits
```

Tiers vs custos médios:
- Starter (50 créditos/mês): ~5 fotos premium ou 25 fotos básicas
- Pro (300/mês): ~30 fotos premium ou 75 fotos com Magnific
- Agency (1500/mês): ~150 fotos premium

---

## 12. Tech stack backend FastAPI

```
Stack:
- Python 3.11+
- FastAPI 0.110+
- Pydantic v2
- SQLAlchemy 2.x + Alembic (migrations)
- AsyncPG (Postgres driver)
- Redis (cache + rate limit)
- Inngest ou Celery (job queue)
- Boto3 / aioboto3 (R2/S3)

Deploy:
- Railway / Fly.io / Render
- Docker container
- Auto-scale 1-5 instances
```

### Estrutura de arquivos
```
api/
├── main.py                  # FastAPI app entry
├── config.py                # Settings + env vars
├── db.py                    # SQLAlchemy session
├── auth/
│   ├── routes.py
│   ├── jwt.py
│   └── deps.py              # Auth dependency
├── personas/
│   ├── routes.py
│   ├── models.py
│   ├── schemas.py
│   └── service.py
├── generations/
│   ├── routes.py
│   ├── models.py
│   ├── schemas.py
│   ├── service.py
│   └── pipeline.py          # Orquestração Freepik + enhancers
├── templates/
├── billing/
│   ├── routes.py
│   ├── stripe_handler.py
│   └── webhook.py
├── uploads/
├── jobs/
│   ├── worker.py            # Background worker
│   └── tasks/
└── tests/
```

---

## 13. Testing endpoints (dev)

```
GET /health                  → { "ok": true, "version": "1.0.0" }
GET /api/debug/freepik-test  → tests Freepik connection
GET /api/debug/db-test       → tests db connection
```

(Apenas em modo dev, autenticado por master key)

---

## 14. Versionamento

- API começa em `v1` (path `/api/v1/...` opcional, default sem versão)
- Breaking changes → bump pra `/api/v2/...`
- Deprecation policy: 6 meses min antes de remover endpoint v1

---

## 15. Documentação automática

FastAPI gera automaticamente:
- Swagger UI em `/docs`
- ReDoc em `/redoc`
- OpenAPI JSON em `/openapi.json`

Lovable pode importar `/openapi.json` direto pra gerar tipos TypeScript do client.
