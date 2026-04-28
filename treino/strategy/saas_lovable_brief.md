# SaaS Cubo — Briefing Completo para Lovable

**Documento mestre pra colar no Lovable**. Tudo que você precisa pra gerar o frontend completo.
**Versão:** 1.0
**Data:** 2026-04-27

---

## 1. PROJECT OVERVIEW

**Nome do produto:** *(TBD — sugestões: Persona Studio / Modulus / Cubo Studio / Refine)*
**One-liner:** "Crie sua influencer IA fotorrealista em segundos. Pipeline de produção que rivaliza Aitana e Olivia Roa."
**Tipo de aplicação:** SaaS B2C/B2B web app
**Modelo de negócio:** Subscription (créditos mensais) + tiers
**Domínio principal:** refinecubo.com.br (agência) + soph.ia.com.br (showcase Sophia)
**Mercado primário:** Brasil → expansão LatAm/EU

### Fundadora: Cubo
Agência brasileira de criação de IA influencers. Sophia é a primeira persona. SaaS permite que outros criadores/agências/brands criem suas próprias IA influencers usando o mesmo pipeline.

---

## 2. BRAND IDENTITY (Cubo)

### 2.1 Color palette

```css
/* Primary — Branco */
--white: #FFFFFF;
--off-white: #FAFAF7;          /* fundos premium, cards */

/* Cinzas (neutros) */
--gray-50: #F5F5F5;             /* hover states */
--gray-100: #E5E5E5;            /* borders, dividers */
--gray-300: #A3A3A3;            /* text secondary */
--gray-600: #525252;            /* text body */
--gray-900: #1A1A1A;            /* text primary, dark mode bg */

/* Laranja Cubo (signature accent) */
--orange-primary: #FF6B1A;      /* CTAs, links, highlights */
--orange-dark: #D44E0F;          /* hover CTAs */
--orange-light: #FFF4ED;         /* fundos sutis, badges */
--orange-muted: #FFD9C2;         /* states secundários */

/* Estados */
--success: #10B981;              /* sucesso */
--error: #EF4444;                /* erro */
--warning: #F59E0B;              /* aviso */
--info: #3B82F6;                 /* info */
```

### 2.2 Typography

```css
/* Display (headlines, hero) */
font-family: "Inter", "Söhne", system-ui, sans-serif;
font-weights: 400, 500, 600, 700, 900;

/* Body (paragraphs, content) */
font-family: "Inter", system-ui, sans-serif;
font-weights: 400, 500;

/* Mono (technical, code, data) */
font-family: "Geist Mono", "JetBrains Mono", monospace;
```

**Hierarquia tipográfica:**
- H1 hero: 64-72px / weight 700 / -0.02em letter-spacing
- H2 section: 40-48px / weight 600 / -0.01em
- H3 card: 24-28px / weight 600 / 0
- Body large: 18px / weight 400 / 1.6 line-height
- Body: 15-16px / weight 400 / 1.5 line-height
- Caption: 13px / weight 500 / 0.01em

### 2.3 Voice & Tone

**Tom:** confiante, técnico mas acessível, premium sem ser arrogante. Brasileiro adulto.

**Faz:**
- "Crie sua influencer IA em minutos."
- "Pipeline de produção. Não é prompt random."
- "700 análises de mercado. 1 plataforma."

**Não faz:**
- "Bem-vindos!" (genérico)
- "Vamos juntos nessa jornada" (cringe)
- "Revolucione seu marketing" (clichê)
- Emojis em CTAs (não combina com premium)

### 2.4 Visual style

**Estilo geral:** Premium tech editorial. Lembrar Linear, Vercel, Stripe — mas com warmth brasileira (laranja).

- **Spacing:** generoso (8px / 16px / 24px / 32px / 48px / 64px / 96px)
- **Corners:** rounded-md (6px) padrão, rounded-2xl (16px) pra cards principais
- **Shadows:** sutis, nunca pesadas. `shadow-sm` ou `shadow-md` max.
- **Animations:** subtle fade + transform. Framer Motion preferred.
- **Imagens:** sempre alta qualidade, never genérico stock
- **Iconografia:** Lucide React (consistente, premium)

### 2.5 Layout patterns

- **Grid system:** 12 colunas, max-width 1280px (premium feeling)
- **Cards:** white bg + shadow-sm + border subtle gray-100
- **Buttons:**
  - Primary: orange bg + white text
  - Secondary: white bg + gray-900 border + gray-900 text
  - Ghost: transparent + gray-600 text
- **Forms:** inputs com label flutuante, foco com ring-orange-primary

---

## 3. USER STORIES (priorizado MVP)

### Personas

**P1 — Creator individual (B2C)**
- Daniel, 27, dropshipper afiliado
- Quer criar IA influencer pra anunciar produtos
- Não tem conhecimento técnico
- Orçamento: R$50-200/mês

**P2 — Agência pequena (B2B)**
- Marina, 32, founder de agência boutique
- Atende 5-10 brands DTC brasileiras
- Quer criar modelos IA dedicadas pra cada cliente
- Orçamento: R$300-1000/mês

**P3 — Brand DTC (B2B)**
- Luiza, 35, head of marketing de brand de skincare
- Quer modelo IA exclusiva pra brand
- Orçamento: R$2-5k/mês

### User stories MVP

**Onboarding (Day 1)**
- [ ] Como creator, quero criar conta com email/Google em <30s
- [ ] Como creator, quero ver tour de 3 passos no primeiro login
- [ ] Como creator, quero subir 1-3 fotos da minha modelo (ou escolher template Sophia)
- [ ] Como creator, quero gerar grid 4 ângulos automaticamente

**Geração (core)**
- [ ] Como creator, quero escolher template de cena (drop-down 25 estilos pré-clusterizados)
- [ ] Como creator, quero ajustar detalhes (outfit cor, locação, mood)
- [ ] Como creator, quero ver progresso da geração em tempo real
- [ ] Como creator, quero gerar 4-6 variações por chamada
- [ ] Como creator, quero baixar fotos em 4K
- [ ] Como creator, quero ver galeria de gerações passadas

**Templates / Library**
- [ ] Como creator, quero ver os 25+ templates extraídos do dataset Aitana
- [ ] Como creator, quero filtrar por categoria (travel, fitness, café, etc)
- [ ] Como creator, quero criar templates próprios e salvar

**Billing**
- [ ] Como creator, quero ver meu saldo de créditos atual
- [ ] Como creator, quero comprar mais créditos / mudar tier
- [ ] Como creator, quero ver histórico de cobranças

**Personas (gestão)**
- [ ] Como creator, quero gerenciar múltiplas personas (Sophia, Maria, etc)
- [ ] Como agência, quero acessar 15 personas (tier Agency)
- [ ] Como creator, quero "salvar" persona com identidade canônica

---

## 4. PAGES / ROUTES

```
/                          → Landing (sales page do SaaS)
/pricing                   → Tiers + comparação
/login                     → Login (Google + email)
/signup                    → Signup
/onboarding                → 3 passos (welcome → upload modelo → primeiro generate)

/app                       → Dashboard logado
  /app/personas            → Lista de personas do user
  /app/personas/new        → Criar nova persona
  /app/personas/[id]       → Editar/visualizar persona
  /app/personas/[id]/edit  → Edit form

/app/generate              → Página principal de geração
  ?template=<id>           → Pre-fill com template selecionado
  ?persona=<id>            → Pre-fill com persona selecionada

/app/generations           → Galeria com todas as gerações
  /app/generations/[id]    → Detail page de 1 geração

/app/templates             → Library de templates (25+)
  /app/templates/[id]      → Detail page (preview + ajustes)

/app/billing               → Saldo + planos + histórico
/app/settings              → Profile + API keys + integrations

/about                     → Cubo + Sophia
/blog                      → Blog (futuro)
/case-studies              → Casos (futuro)
```

---

## 5. COMPONENTS REQUIRED

### Layout
- `Sidebar` — fixed left, with nav items + user menu bottom
- `TopBar` — search + notifications + user avatar
- `Footer` — links, redes sociais, legal

### Generation flow
- `TemplateGallery` — grid de templates com preview
- `TemplateDetail` — preview grande + ajustes (sliders + dropdowns)
- `GenerationProgress` — barra de progresso + ETA + status text
- `GenerationCard` — thumbnail + info + actions (download, regenerate, delete)
- `GenerationGrid` — masonry grid de gerações

### Persona management
- `PersonaCard` — avatar circular + nome + ações
- `PersonaEditor` — form com upload + persona settings
- `PersonaCanonicalGrid` — preview do grid 4 ângulos

### Billing
- `CreditCounter` — top right, com progress bar
- `PricingTable` — 4 tiers (Starter / Pro / Agency / Enterprise)
- `BillingHistory` — table com invoices

### Marketing pages
- `Hero` — full bleed + headline + CTA
- `FeatureGrid` — 6-9 features com ícone
- `Testimonial` — quote + persona + foto
- `LogoCloud` — brands que usam (futuro: real)
- `FAQ` — accordion
- `CTA` — banner final

### Forms / inputs
- `Button` (primary, secondary, ghost, destructive)
- `Input` (text, email, password)
- `Textarea`
- `Select` (dropdown moderna estilo Linear)
- `Slider` (pra creativity, hdr, etc do Magnific)
- `ImageUpload` (drag-drop com preview)
- `Toggle` (switch)
- `Checkbox` / `RadioGroup`

---

## 6. AUTH FLOW

### Stack
- **Auth provider:** Clerk (mais simples) ou Supabase Auth
- **Sessões:** JWT stored em httpOnly cookies
- **Métodos:** Google OAuth (primary), email/password (secondary), magic link

### Flow
1. User clica "Sign up free" no landing
2. Modal de signup → Google ou email
3. Email verification
4. Onboarding (3 passos)
5. App principal

### Permissões / Tiers
```
Free          → 3 gerações teste, no save persona
Starter $30   → 50 fotos/mês, 1 persona, templates basic
Pro $97       → 300 fotos/mês, 3 personas, todos templates, Magnific
Agency $297   → 1500 fotos/mês, 15 personas, white-label, API access
Enterprise    → Custom (modelo dedicada exclusiva, suporte)
```

---

## 7. API INTEGRATION

### Backend URL (a definir após deploy)
```
Production: https://api.refinecubo.com.br
Development: http://localhost:8000
```

### Auth header
```
Authorization: Bearer <JWT_TOKEN>
```

### Endpoints principais (referência completa em `saas_api_spec.md`)

#### Auth
```
POST /api/auth/signup        → email + password
POST /api/auth/login         → returns JWT
POST /api/auth/google        → OAuth callback
POST /api/auth/refresh       → refresh JWT
POST /api/auth/logout
GET  /api/auth/me            → current user info
```

#### Personas
```
POST   /api/personas         → create new (with image upload)
GET    /api/personas         → list user's personas
GET    /api/personas/:id     → get one
PATCH  /api/personas/:id     → update
DELETE /api/personas/:id     → delete
POST   /api/personas/:id/generate-grid  → generate 4-angle canonical grid
```

#### Generations (core)
```
POST   /api/generations              → create job (returns job_id)
  body: {
    persona_id: string,
    template_id?: string,
    prompt?: string,
    aspect_ratio: "1:1"|"3:4"|"9:16"|"4:5",
    resolution: "1K"|"2K"|"4K",
    num_variations: 1|2|4|6,
    options?: { magnific: bool, etc }
  }
  returns: { job_id, status: "queued" }

GET    /api/generations              → list user's
GET    /api/generations/:id          → get one (with images urls)
DELETE /api/generations/:id

WebSocket /ws/generations/:job_id    → real-time status updates
  events: queued → processing → enhancing → upscaling → completed | failed
```

#### Templates
```
GET    /api/templates                → list 25+ templates (from clustering)
GET    /api/templates/:id            → get one with preview
POST   /api/templates                → user creates custom (Pro+)
DELETE /api/templates/:id            → delete custom
```

#### Billing
```
GET    /api/billing/balance          → credits remaining
GET    /api/billing/history          → invoices
POST   /api/billing/checkout         → Stripe checkout (returns URL)
POST   /api/billing/portal           → Stripe portal (returns URL)
GET    /api/billing/tier             → current tier
```

#### Uploads
```
POST   /api/uploads/persona-photo    → upload reference photo (S3 signed URL)
POST   /api/uploads/template-preview → upload template preview
```

### Error codes
```
401 — Unauthorized
403 — Forbidden (tier limit)
404 — Not found
422 — Validation
429 — Rate limit / credits exhausted
500 — Server error
```

### Polling pattern (sem WebSocket)
```ts
const pollGeneration = async (jobId: string) => {
  while (true) {
    const r = await fetch(`/api/generations/${jobId}`)
    const data = await r.json()
    if (data.status === 'completed' || data.status === 'failed') return data
    await sleep(3000)
  }
}
```

---

## 8. DESIGN DIRECTION (Premium Tech)

**References:**
- Linear (linear.app) — typography, spacing, sidebar
- Stripe (stripe.com) — landing patterns, gradients sutis
- Vercel (vercel.com) — dark mode polished, technical aesthetic
- Persona AI (personaai.com — se existir) — direct competitor reference

**Key aesthetic decisions:**
- **Light mode default** (white + off-white background)
- Dark mode optional (gray-900 + gray-700)
- Generosidade de espaçamento (não cramming)
- Imagens always 4K (nunca degraded)
- Animações: fadeIn 200ms + slide subtle
- Hero do landing: foto/grid da Sophia em destaque (vitrine viva)
- Sidebar: ícones Lucide minimalistas + labels sublabels
- Empty states: ilustrações abstratas + CTA orange

**Anti-padrões:**
- ❌ Gradient backgrounds (parece 2018)
- ❌ Stock photos genéricas
- ❌ Animações pesadas (rotação 3D, parallax exagerado)
- ❌ "Hi! Welcome 👋" headers
- ❌ 100 features na home (escolher 6-9 max)

---

## 9. INITIAL PROMPTS PRA COLAR NO LOVABLE

### Prompt 1 — Setup base

```
Build a premium SaaS web application called "Cubo Studio" (placeholder name) for creating photorealistic AI influencers.

Tech stack:
- Next.js 14 App Router + TypeScript
- Tailwind CSS + shadcn/ui components
- Lucide React icons
- Framer Motion for animations
- Supabase Auth + Postgres + Storage
- Stripe for billing

Brand identity:
- Colors: white (#FFFFFF), off-white (#FAFAF7), grays (50-900), orange primary (#FF6B1A), orange dark (#D44E0F)
- Typography: Inter for everything, Geist Mono for technical/code
- Premium tech editorial aesthetic (think Linear + Stripe + Vercel)
- Light mode default, optional dark mode

Initial pages:
- Landing (/) — hero with Sophia showcase, features grid, pricing teaser, CTA
- Pricing (/pricing) — 4 tiers (Starter $30, Pro $97, Agency $297, Enterprise)
- App dashboard (/app) — sidebar layout with main content area
- Login/Signup pages — clean modal-style

Backend API base URL: https://api.refinecubo.com.br (placeholder)
Auth: JWT bearer in Authorization header

Generate with TypeScript strict mode, all components in PascalCase, files in kebab-case.
Layout components in /components/layout/, UI in /components/ui/, business logic in /components/features/.
```

### Prompt 2 — Landing page

```
Create the landing page (/) for Cubo Studio.

Sections (top to bottom):
1. Top nav: Cubo logo (text wordmark) on left, "Pricing | Sign in | Get started (orange CTA)" on right
2. Hero:
   - Eyebrow: "AI INFLUENCER STUDIO"
   - Headline (h1): "Crie sua influencer IA em minutos. Não em meses."
   - Subhead: "Pipeline de produção que rivaliza Aitana e Olivia Roa. Para creators, agências e brands."
   - CTAs: "Começar grátis →" (orange primary) + "Ver demo Sophia ↗" (outline)
   - Visual: full-width grid (3x2) of Sophia editorial photos
3. Logo cloud: "USED BY" + 8 brand logos (placeholders)
4. Features grid (6 features):
   - 🎨 Pipeline 4K que rivaliza estúdios profissionais
   - ⚡ Geração em 3-5 minutos por foto
   - 🎯 25+ templates pré-clusterizados (lifestyle, travel, fitness, OOTD)
   - 🔒 Identidade fixa garantida (nunca mais "uncanny valley")
   - 📦 Carrosséis automáticos (1 sessão = 12 posts)
   - 🤝 White-label para agências
5. Showcase: split section "Antes (sua IA)" vs "Depois (Cubo Studio)" — slider before/after
6. Testimonials (placeholder real later)
7. Pricing teaser: 4 tier cards with "Starter $30 · Pro $97 · Agency $297 · Enterprise"
8. Final CTA banner: full-width orange-light bg, "Pronto pra criar sua IA?" + "Começar grátis →"
9. Footer: Cubo logo + columns (Product, Company, Resources, Legal) + copyright

Use Framer Motion for fade-in on scroll. Generous whitespace. Premium feel.
Headlines in 64-72px Inter weight 700. Body 18px line-height 1.6.
```

### Prompt 3 — App dashboard

```
Create the authenticated app dashboard (/app).

Layout: Sidebar (fixed left, 240px wide) + main content area.

Sidebar:
- Top: Cubo logo + workspace selector
- Nav (Lucide icons + labels):
  - Home (LayoutDashboard)
  - Personas (Users)
  - Generate (Sparkles) ← main action, slight orange highlight
  - Library (FolderOpen)
  - Templates (LayoutTemplate)
  - Generations (Image)
  - Billing (CreditCard)
  - Settings (Settings)
- Bottom: User menu (avatar + name + tier badge "PRO")

Main content (Home):
- Top bar: Search input (cmd+k) + notifications bell + credit counter ("Saldo: 247 créditos")
- Hero card: "Bem-vindo de volta, [Nome]. Hoje você tem 247 créditos." + "Generate now" CTA
- Stats grid (4 cards): Total generations / This month / Avg quality score / Personas
- Recent generations: horizontal carousel of last 8 thumbnails
- Suggested templates: grid 6 cards (preview + name + category)
- Quick actions panel right: "Create persona", "Browse templates", "Buy credits"

Use shadcn/ui Card, Tabs, Sheet, Dialog. Loading states with shimmer skeletons.
```

### Prompt 4 — Generate flow

```
Create the generation flow page (/app/generate).

Layout: 2-column. Left (40%) = controls. Right (60%) = preview/output.

Left column (controls):
1. Persona selector: dropdown "Sophia (default)" or list of saved personas + "Create new"
2. Template selector: button "Choose template ↓" → opens modal with 25+ templates
3. Tabs: "Quick" / "Advanced"
   Quick tab:
   - Aspect ratio: pill group (1:1 / 3:4 / 9:16 / 4:5)
   - Resolution: pill group (1K / 2K / 4K)
   - Variations: pill group (1 / 2 / 4 / 6)
   Advanced tab:
   - Prompt textarea (optional override)
   - Magnific upscale toggle
   - Custom seed
4. Cost estimator: "Esta geração custará 12 créditos" (orange box)
5. CTA button (full width, orange): "Gerar (12 créditos) →"

Right column (output):
- Empty state: "Sua geração aparecerá aqui" + ilustração abstrata
- Loading state: progress bar + "Etapa 2/4: Refinando pele... ~2min"
- Result state: 4-6 thumbnails grid with download/regenerate/save buttons

Add real-time status updates via WebSocket or polling (3s interval).
```

### Prompt 5 — Templates library

```
Create the templates library page (/app/templates).

Top: filter bar
- Category pills: All / Lifestyle / Travel / Fitness / Editorial / Café / Beach / Boudoir / Event
- Search input
- Sort dropdown (Most popular / Newest / Trending)

Body: masonry grid (3 columns desktop, 2 tablet, 1 mobile)
Each card:
- 4:5 preview image (template hero shot)
- Hover: shows secondary preview (alternate angle from same template cluster)
- Below image:
  - Template name (e.g., "Mediterranean Travel — Coastal Sunset")
  - Category badge (e.g., "Travel" small pill orange)
  - Stats: "↑ 234 uses" / "★ 4.8"
  - CTA: "Use template →"

Click card opens detail modal:
- Large preview (4:5)
- Description
- Examples (4-6 thumbnails)
- "Use this template" CTA → goes to /app/generate?template=<id>
- "Save to favorites" button

Initial templates (use placeholders for now):
1. Mediterranean Travel
2. Brazilian Beach Editorial
3. Café Lifestyle Selfie
4. Fitness Mirror Selfie
5. OOTD Streetwear Europe
6. Boudoir Slip Dress
7. Editorial Studio Close-up
8. Walking Street Cinematic
9. Hotel Suite Glamour
10. Festival Cultural (Feria-style)
11. Ski/Winter Alpine
12. Roof Sunset Cocktail
... (placeholder até clusterização final dos 718 JSONs)
```

---

## 10. INTEGRATIONS NEEDED

### Critical (MVP)
- [ ] **Supabase** (auth + db + storage) — free tier OK início
- [ ] **Stripe** (billing) — usar Stripe Customer Portal pra evitar custom UI
- [ ] **Backend API** (FastAPI hosted em Railway/Fly.io) — orquestra Freepik
- [ ] **Cloudflare R2** ou Supabase Storage — armazenar gerações
- [ ] **Vercel** (deploy frontend) — auto deploy from GitHub

### Pós-MVP (Nice-to-have)
- [ ] **Inngest** — job queue avançada
- [ ] **PostHog** — analytics
- [ ] **Resend** — emails transacionais
- [ ] **Sentry** — error tracking
- [ ] **Cal.com** — bookings pra Enterprise tier

---

## 11. ENV VARIABLES (Lovable / Production)

```env
# Database
DATABASE_URL=postgresql://...
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_KEY=...

# Auth
JWT_SECRET=...
NEXTAUTH_URL=https://app.refinecubo.com.br
NEXTAUTH_SECRET=...

# Backend API
NEXT_PUBLIC_API_URL=https://api.refinecubo.com.br

# Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
NEXT_PUBLIC_STRIPE_PUBLIC_KEY=pk_live_...

# Storage
R2_ACCESS_KEY=...
R2_SECRET_KEY=...
R2_BUCKET=cubo-generations

# Backend pipeline (referência — usado pelo backend FastAPI)
FREEPIK_API_KEY=FPSX...
ANTHROPIC_API_KEY=sk-ant-... # se usar Claude pra análise
```

---

## 12. ROADMAP MVP (4 semanas)

### Semana 1 — Setup foundation
- [ ] Lovable: gerar boilerplate landing + auth + dashboard skeleton
- [ ] Supabase: setup db + auth (Google + email)
- [ ] Stripe: configurar produtos + webhooks
- [ ] Backend FastAPI: boilerplate em Railway/Fly.io
- [ ] Domain setup: app.refinecubo.com.br + api.refinecubo.com.br

### Semana 2 — Core flows
- [ ] Onboarding 3 steps
- [ ] Personas CRUD
- [ ] Generate flow (sem queue ainda — sync first)
- [ ] Galeria de gerações
- [ ] Billing tier check

### Semana 3 — Polish + Templates
- [ ] Library de templates (estática primeiro, ler do JSON)
- [ ] WebSocket pra progress real-time
- [ ] Stripe portal integrado
- [ ] Error handling + toast notifications
- [ ] Empty states + loading states polished

### Semana 4 — Pre-launch
- [ ] Beta closed pra 10-20 usuários (waitlist)
- [ ] Email transacional Resend (welcome, generation done, etc)
- [ ] Landing public + pricing page final
- [ ] Press kit page
- [ ] Marketing email sequence
- [ ] Launch

---

## 13. ASSETS NECESSÁRIOS PRO LOVABLE

### Imagens (a gerar antes / placeholder)
- [ ] 6 fotos editorial Sophia (hero + features) — 1920×1200
- [ ] 12 fotos de templates (preview cards) — 800×1000 (4:5)
- [ ] 1 vídeo loop hero (4-6s, autoplay muted) — 1920×1080
- [ ] Logo Cubo (SVG light + dark)
- [ ] Favicon (32x32 + 192x192)

### Copys (a escrever)
- [ ] Hero headlines (3 variações pra A/B test)
- [ ] 6 features descriptions (40-60 chars cada)
- [ ] 4 pricing tier descriptions
- [ ] FAQ (8-10 perguntas)
- [ ] Email transacional (welcome, generation complete, payment confirmation, etc)
- [ ] Footer copy + legal (privacy, terms — pode usar boilerplate)

---

## 14. NOMES SUGERIDOS PRO SAAS (final TBD)

Ranqueados:
1. **Refine** (refine.app / refine.io) — alinha com refinecubo.com.br
2. **Cubo Studio** (cubo.studio) — extensão direta da agência
3. **Persona** (persona.ai) — direto, mas saturado
4. **Modulus** (modulus.ai) — disponível, sounds tech
5. **Iaduna** (iaduna.com) — fusion IA + duna (curitiba? Brasil?)
6. **Neura** (neura.app) — disponível
7. **Replikai** (replikai.com)
8. **PersonaForge** (personaforge.app)

**Recomendação:** **Refine** (refinecubo.com.br/app ou refine.studio). Alinha com a agência, é simples, premium-coded.

---

## Próximos arquivos relacionados

- `saas_api_spec.md` — especificação completa OpenAPI dos endpoints (consumido pelo Lovable + backend)
- `api/main.py` — backend FastAPI starter pronto pra deploy
- `content_clusters.md` — 25+ templates extraídos dos 718 JSONs (carregar como seed do db)
