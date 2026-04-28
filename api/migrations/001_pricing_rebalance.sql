-- ════════════════════════════════════════════════════════════════
-- Migration: pricing_rebalance (2026-04-28)
-- ════════════════════════════════════════════════════════════════
-- Suporta a nova estrutura de planos Cubo / Refine:
--   - 4 tiers mensais (Starter R$27, Creator R$59, Pro R$129, Studio R$799)
--   - 4 tiers anuais (-30% + bônus boas-vindas, repostos via cron mensal)
--   - 4 packs de boost (top-up avulso)
--   - 6 add-ons one-shot (Kling V3 +áudio, LoRA, Voice Clone, etc.)
--   - Daily caps por modelo+plano (anti-abuso)
-- ════════════════════════════════════════════════════════════════

BEGIN;

-- ─── 1. Profiles: novas colunas pra distinguir mensal/anual ───
ALTER TABLE profiles
    ADD COLUMN IF NOT EXISTS subscription_interval TEXT
        CHECK (subscription_interval IN ('month', 'year') OR subscription_interval IS NULL);

ALTER TABLE profiles
    ADD COLUMN IF NOT EXISTS subscription_tier_key TEXT;
    -- Ex: 'starter_monthly', 'pro_yearly', etc. Usado pelo cron pra reposição.

CREATE INDEX IF NOT EXISTS idx_profiles_yearly_active
    ON profiles (subscription_interval, subscription_tier_key)
    WHERE subscription_interval = 'year';


-- ─── 2. Daily usage: contagem por (user, modelo, dia) pra cap ───
CREATE TABLE IF NOT EXISTS daily_usage (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID NOT NULL,
    model       TEXT NOT NULL,
    used_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Não FK pra evitar cascata em delete de profile
    CONSTRAINT daily_usage_user_id_idx UNIQUE (user_id, model, used_at)
);

CREATE INDEX IF NOT EXISTS idx_daily_usage_user_model_time
    ON daily_usage (user_id, model, used_at DESC);

CREATE INDEX IF NOT EXISTS idx_daily_usage_cleanup
    ON daily_usage (used_at)
    WHERE used_at < NOW() - INTERVAL '7 days';


-- ─── 3. Add-on purchases: registros de compras one-shot ───
CREATE TABLE IF NOT EXISTS addon_purchases (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    addon_id            TEXT NOT NULL,
    -- ex: 'kling_v3_pro_10s_audio', 'magnific_8k', 'lora_medium', etc.
    amount_brl          NUMERIC(10, 2) NOT NULL,
    stripe_session_id   TEXT,
    used_at             TIMESTAMPTZ,
    -- Quando o crédito do add-on foi consumido (NULL = ainda não usado)
    metadata            JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_addon_purchases_user
    ON addon_purchases (user_id, used_at);

CREATE INDEX IF NOT EXISTS idx_addon_purchases_unused
    ON addon_purchases (user_id, addon_id)
    WHERE used_at IS NULL;


-- ─── 4. Migra tiers antigos pra estrutura nova ───
-- Tier antigo 'starter' (R$47/500) → mantém id 'starter' pero subscription_tier_key='starter_monthly'
-- Quem estiver no antigo 'agency' migra pra 'studio'
UPDATE profiles
   SET tier = 'studio'
 WHERE tier = 'agency';

-- Atualiza subscription_tier_key dos clientes existentes (assume mensal)
UPDATE profiles
   SET subscription_interval = 'month',
       subscription_tier_key = tier || '_monthly'
 WHERE tier IN ('starter', 'creator', 'pro', 'studio')
   AND subscription_tier_key IS NULL
   AND stripe_customer_id IS NOT NULL;


-- ─── 5. View útil pra dashboards ───
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
    -- Soma de add-ons no último mês
    COALESCE((
        SELECT SUM(amount_brl)
          FROM addon_purchases ap
         WHERE ap.user_id = p.id
           AND ap.created_at > NOW() - INTERVAL '30 days'
    ), 0)             AS addons_last_30d_brl,
    -- Quantidade de gerações no último mês
    COALESCE((
        SELECT COUNT(*)
          FROM generations g
         WHERE g.user_id = p.id
           AND g.created_at > NOW() - INTERVAL '30 days'
    ), 0)             AS generations_last_30d
FROM profiles p
WHERE p.subscription_tier_key IS NOT NULL;


COMMIT;
