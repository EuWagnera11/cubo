-- ════════════════════════════════════════════════════════════════
-- Cubo / Refine — Initial Schema (consolidated)
-- ════════════════════════════════════════════════════════════════
-- Schema completo do backend. Inclui:
--   • Auth/Profile (linkado a Supabase auth.users via trigger)
--   • Generations + Personas + Templates + Worlds + Presets
--   • Audio (TTS/Music/SFX/Lipsync) + Voices + Music Tracks
--   • Edit Jobs + Batch Jobs + Recreate Jobs
--   • Drive Imports + Learned Styles
--   • Content Calendars + Content Packs
--   • Pricing rebalance: subscription_interval, daily_usage, addon_purchases
--
-- Aplicar UMA VEZ em banco vazio. Idempotente (CREATE IF NOT EXISTS).
-- ════════════════════════════════════════════════════════════════

BEGIN;

-- ─── Extensões ───
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()


-- ════════════════════════════════════════════════════════════════
--                          PROFILES (auth)
-- ════════════════════════════════════════════════════════════════
-- Linkado ao auth.users do Supabase. Trigger cria profile automático
-- ao registrar novo user.

CREATE TABLE IF NOT EXISTS profiles (
    id                      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email                   TEXT,
    tier                    TEXT NOT NULL DEFAULT 'free'
                                CHECK (tier IN ('free', 'starter', 'creator', 'pro', 'studio', 'admin')),
    credits                 INTEGER NOT NULL DEFAULT 0 CHECK (credits >= 0),
    role                    TEXT NOT NULL DEFAULT 'creator'
                                CHECK (role IN ('creator', 'admin')),
    stripe_customer_id      TEXT,
    subscription_interval   TEXT
                                CHECK (subscription_interval IN ('month', 'year') OR subscription_interval IS NULL),
    subscription_tier_key   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profiles_email ON profiles (email);
CREATE INDEX IF NOT EXISTS idx_profiles_stripe_customer ON profiles (stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_profiles_yearly_active
    ON profiles (subscription_interval, subscription_tier_key)
    WHERE subscription_interval = 'year';

-- Trigger: cria profile automático ao registrar user
CREATE OR REPLACE FUNCTION handle_new_user() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email)
    VALUES (NEW.id, NEW.email)
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION handle_new_user();


-- ════════════════════════════════════════════════════════════════
--                         PERSONAS / TEMPLATES
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personas (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name                    TEXT NOT NULL,
    description             TEXT,
    reference_image_url     TEXT,
    canonical_grid_url      TEXT,
    attributes              JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personas_user ON personas (user_id, created_at DESC);


CREATE TABLE IF NOT EXISTS templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT,
    prompt          TEXT NOT NULL,
    category        TEXT,
    is_public       BOOLEAN NOT NULL DEFAULT true,
    uses_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_templates_category ON templates (category, is_public);


-- ════════════════════════════════════════════════════════════════
--                         WORLDS / MODEL PRESETS
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS worlds (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES profiles(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    description         TEXT,
    category            TEXT,
    prompt_template     TEXT NOT NULL,
    reference_images    TEXT[] DEFAULT '{}',
    is_public           BOOLEAN NOT NULL DEFAULT false,
    uses_count          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_worlds_public ON worlds (is_public, uses_count DESC);
CREATE INDEX IF NOT EXISTS idx_worlds_user ON worlds (user_id, created_at DESC);


CREATE TABLE IF NOT EXISTS model_presets (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL,
    description             TEXT,
    category                TEXT,
    gender                  TEXT,
    reference_image_url     TEXT,
    canonical_grid_url      TEXT,
    uses_count              INTEGER NOT NULL DEFAULT 0,
    rating                  NUMERIC(3, 2) DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_presets_category ON model_presets (category, gender);


-- ════════════════════════════════════════════════════════════════
--                       MUSIC / VOICES (catalog)
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS music_tracks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES profiles(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    genre           TEXT,
    mood            TEXT,
    duration_seconds INTEGER,
    is_public       BOOLEAN NOT NULL DEFAULT false,
    uses_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_music_genre_mood ON music_tracks (genre, mood, is_public);


CREATE TABLE IF NOT EXISTS voices (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID REFERENCES profiles(id) ON DELETE CASCADE,
    name                    TEXT NOT NULL,
    description             TEXT,
    provider                TEXT NOT NULL DEFAULT 'freepik',
    external_voice_id       TEXT,
    is_clone                BOOLEAN NOT NULL DEFAULT false,
    is_public               BOOLEAN NOT NULL DEFAULT false,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voices_user ON voices (user_id, created_at DESC);


-- ════════════════════════════════════════════════════════════════
--                         DRIVE / LEARNED STYLES
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS drive_imports (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    source_type         TEXT NOT NULL,
    source_url          TEXT NOT NULL,
    folder_name         TEXT,
    total_files         INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'importing', 'ready', 'failed')),
    storage_paths       TEXT[] DEFAULT '{}',
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drive_imports_user ON drive_imports (user_id, created_at DESC);


CREATE TABLE IF NOT EXISTS learned_styles (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    drive_import_id         UUID REFERENCES drive_imports(id) ON DELETE SET NULL,
    name                    TEXT NOT NULL,
    description             TEXT,
    status                  TEXT NOT NULL DEFAULT 'analyzing'
                                CHECK (status IN ('analyzing', 'ready', 'failed')),
    prompt_template         TEXT NOT NULL DEFAULT '',
    example_count           INTEGER NOT NULL DEFAULT 0,
    example_paths           TEXT[] DEFAULT '{}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_learned_styles_user ON learned_styles (user_id, created_at DESC);


-- ════════════════════════════════════════════════════════════════
--                         GENERATIONS
-- ════════════════════════════════════════════════════════════════
-- Tabela central: cada geração de imagem/vídeo vira uma row aqui.

CREATE TABLE IF NOT EXISTS recreate_jobs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    persona_id              UUID REFERENCES personas(id) ON DELETE SET NULL,
    drive_import_id         UUID REFERENCES drive_imports(id) ON DELETE SET NULL,
    status                  TEXT NOT NULL DEFAULT 'queued'
                                CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    total_files             INTEGER NOT NULL DEFAULT 0,
    options                 JSONB DEFAULT '{}'::jsonb,
    generation_ids          UUID[] DEFAULT '{}',
    total_credits_used      INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recreate_jobs_user ON recreate_jobs (user_id, created_at DESC);


CREATE TABLE IF NOT EXISTS generations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    persona_id              UUID REFERENCES personas(id) ON DELETE SET NULL,
    template_id             UUID REFERENCES templates(id) ON DELETE SET NULL,
    learned_style_id        UUID REFERENCES learned_styles(id) ON DELETE SET NULL,
    recreate_job_id         UUID REFERENCES recreate_jobs(id) ON DELETE SET NULL,
    source_image_path       TEXT,
    status                  TEXT NOT NULL DEFAULT 'queued'
                                CHECK (status IN ('queued', 'processing', 'enhancing', 'upscaling', 'completed', 'failed')),
    prompt                  TEXT NOT NULL DEFAULT '',
    aspect_ratio            TEXT,
    resolution              TEXT,
    num_variations          INTEGER NOT NULL DEFAULT 1,
    credits_used            INTEGER NOT NULL DEFAULT 0,
    media_type              TEXT NOT NULL DEFAULT 'image'
                                CHECK (media_type IN ('image', 'video')),
    image_urls              TEXT[] DEFAULT '{}',
    video_urls              TEXT[] DEFAULT '{}',
    completed_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generations_user_created ON generations (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generations_status ON generations (status, created_at);
CREATE INDEX IF NOT EXISTS idx_generations_persona ON generations (persona_id, created_at DESC)
    WHERE persona_id IS NOT NULL;


-- ════════════════════════════════════════════════════════════════
--                         BATCH / EDIT JOBS
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS batch_jobs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    persona_id              UUID REFERENCES personas(id) ON DELETE SET NULL,
    type                    TEXT NOT NULL
                                CHECK (type IN ('batch_image', 'batch_video')),
    config                  JSONB DEFAULT '{}'::jsonb,
    status                  TEXT NOT NULL DEFAULT 'queued'
                                CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    total_files             INTEGER NOT NULL DEFAULT 0,
    total_credits_used      INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_batch_jobs_user ON batch_jobs (user_id, created_at DESC);


CREATE TABLE IF NOT EXISTS edit_jobs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    type                    TEXT NOT NULL,
    -- ex: 'inpaint', 'outpaint', 'remove_object', 'sketch_to_image',
    --     'style_transfer', 'replace_background', 'expand', 'colorize'
    status                  TEXT NOT NULL DEFAULT 'processing'
                                CHECK (status IN ('processing', 'completed', 'failed')),
    source_image_url        TEXT NOT NULL,
    mask_url                TEXT,
    prompt                  TEXT,
    reference_style_url     TEXT,
    options                 JSONB DEFAULT '{}'::jsonb,
    result_urls             TEXT[] DEFAULT '{}',
    credits_used            INTEGER NOT NULL DEFAULT 0,
    completed_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_edit_jobs_user ON edit_jobs (user_id, created_at DESC);


-- ════════════════════════════════════════════════════════════════
--                         AUDIO GENERATIONS
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS audio_generations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    type                    TEXT NOT NULL
                                CHECK (type IN ('tts', 'music', 'sound_effect', 'lip_sync', 'audio_isolation')),
    status                  TEXT NOT NULL DEFAULT 'processing'
                                CHECK (status IN ('processing', 'completed', 'failed')),
    text_input              TEXT,
    voice_id                TEXT,
    voice_preset            TEXT,
    language                TEXT,
    music_genre             TEXT,
    music_mood              TEXT,
    duration_seconds        INTEGER,
    source_video_url        TEXT,
    reference_audio_url     TEXT,
    output_url              TEXT,
    credits_used            INTEGER NOT NULL DEFAULT 0,
    metadata                JSONB DEFAULT '{}'::jsonb,
    completed_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audio_user ON audio_generations (user_id, created_at DESC);


-- ════════════════════════════════════════════════════════════════
--                       CONTENT CALENDAR
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS content_packs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key                 TEXT UNIQUE NOT NULL,
    name                TEXT NOT NULL,
    description         TEXT,
    template_pattern    JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_public           BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS content_calendars (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    persona_id              UUID REFERENCES personas(id) ON DELETE SET NULL,
    name                    TEXT NOT NULL,
    brief                   TEXT,
    start_date              DATE NOT NULL,
    end_date                DATE NOT NULL,
    pack_key                TEXT,
    n_posts                 INTEGER NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'queued'
                                CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    posts                   JSONB DEFAULT '[]'::jsonb,
    generation_ids          UUID[] DEFAULT '{}',
    total_credits_used      INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calendars_user ON content_calendars (user_id, created_at DESC);


-- ════════════════════════════════════════════════════════════════
--                       PRICING / SUBSCRIPTIONS
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS daily_usage (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    used_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_daily_usage_user_model_time
    ON daily_usage (user_id, model, used_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_usage_cleanup
    ON daily_usage (used_at);


CREATE TABLE IF NOT EXISTS addon_purchases (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    addon_id            TEXT NOT NULL,
    -- ex: 'kling_v3_pro_10s_audio', 'magnific_8k', 'lora_medium', etc.
    amount_brl          NUMERIC(10, 2) NOT NULL,
    stripe_session_id   TEXT,
    used_at             TIMESTAMPTZ,
    metadata            JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_addon_purchases_user
    ON addon_purchases (user_id, used_at);
CREATE INDEX IF NOT EXISTS idx_addon_purchases_unused
    ON addon_purchases (user_id, addon_id)
    WHERE used_at IS NULL;


-- ════════════════════════════════════════════════════════════════
--                          VIEWS
-- ════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW v_active_subscriptions AS
SELECT
    p.id              AS user_id,
    p.email,
    p.tier,
    p.subscription_interval,
    p.subscription_tier_key,
    p.credits         AS current_credits,
    p.stripe_customer_id,
    p.created_at,
    COALESCE((
        SELECT SUM(amount_brl)
          FROM addon_purchases ap
         WHERE ap.user_id = p.id
           AND ap.created_at > NOW() - INTERVAL '30 days'
    ), 0)             AS addons_last_30d_brl,
    COALESCE((
        SELECT COUNT(*)
          FROM generations g
         WHERE g.user_id = p.id
           AND g.created_at > NOW() - INTERVAL '30 days'
    ), 0)             AS generations_last_30d
FROM profiles p
WHERE p.subscription_tier_key IS NOT NULL;


-- ════════════════════════════════════════════════════════════════
--                          ROW LEVEL SECURITY
-- ════════════════════════════════════════════════════════════════
-- Habilita RLS — backend usa service_role pra bypass; frontend
-- (lovable-cubo) usa anon key e respeita as policies abaixo.

ALTER TABLE profiles            ENABLE ROW LEVEL SECURITY;
ALTER TABLE personas            ENABLE ROW LEVEL SECURITY;
ALTER TABLE generations         ENABLE ROW LEVEL SECURITY;
ALTER TABLE batch_jobs          ENABLE ROW LEVEL SECURITY;
ALTER TABLE edit_jobs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE audio_generations   ENABLE ROW LEVEL SECURITY;
ALTER TABLE drive_imports       ENABLE ROW LEVEL SECURITY;
ALTER TABLE learned_styles      ENABLE ROW LEVEL SECURITY;
ALTER TABLE recreate_jobs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_calendars   ENABLE ROW LEVEL SECURITY;
ALTER TABLE addon_purchases     ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_usage         ENABLE ROW LEVEL SECURITY;
ALTER TABLE voices              ENABLE ROW LEVEL SECURITY;
ALTER TABLE worlds              ENABLE ROW LEVEL SECURITY;

-- Policies: usuário só vê/edita seus próprios dados
DROP POLICY IF EXISTS "users_own_profile" ON profiles;
CREATE POLICY "users_own_profile" ON profiles
    FOR ALL TO authenticated
    USING (auth.uid() = id);

DROP POLICY IF EXISTS "users_own_personas" ON personas;
CREATE POLICY "users_own_personas" ON personas
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_generations" ON generations;
CREATE POLICY "users_own_generations" ON generations
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_batch_jobs" ON batch_jobs;
CREATE POLICY "users_own_batch_jobs" ON batch_jobs
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_edit_jobs" ON edit_jobs;
CREATE POLICY "users_own_edit_jobs" ON edit_jobs
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_audio" ON audio_generations;
CREATE POLICY "users_own_audio" ON audio_generations
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_drive_imports" ON drive_imports;
CREATE POLICY "users_own_drive_imports" ON drive_imports
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_learned_styles" ON learned_styles;
CREATE POLICY "users_own_learned_styles" ON learned_styles
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_recreate_jobs" ON recreate_jobs;
CREATE POLICY "users_own_recreate_jobs" ON recreate_jobs
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_calendars" ON content_calendars;
CREATE POLICY "users_own_calendars" ON content_calendars
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_addons" ON addon_purchases;
CREATE POLICY "users_own_addons" ON addon_purchases
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_own_daily_usage" ON daily_usage;
CREATE POLICY "users_own_daily_usage" ON daily_usage
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

-- Voices: pode ver públicas + as próprias
DROP POLICY IF EXISTS "voices_visible" ON voices;
CREATE POLICY "voices_visible" ON voices
    FOR SELECT TO authenticated
    USING (is_public = true OR user_id = auth.uid());

DROP POLICY IF EXISTS "voices_own_write" ON voices;
CREATE POLICY "voices_own_write" ON voices
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);

-- Worlds: pode ver públicos + os próprios
DROP POLICY IF EXISTS "worlds_visible" ON worlds;
CREATE POLICY "worlds_visible" ON worlds
    FOR SELECT TO authenticated
    USING (is_public = true OR user_id = auth.uid());

DROP POLICY IF EXISTS "worlds_own_write" ON worlds;
CREATE POLICY "worlds_own_write" ON worlds
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);


COMMIT;
