-- ════════════════════════════════════════════════════════════════
-- 002 — Tool routing, projects, persona bundles, prompt envelopes
-- ════════════════════════════════════════════════════════════════
-- Adiciona infra pra refatoração da rota /generations:
--   • Discriminador `tool + op` em generations
--   • Versionamento de gerações (parent_id) e bucketing por projeto
--   • Refs estruturadas (jsonb) com role (subject/outfit/scene/style/pose)
--   • Persona como bundle de imagens (ref_image_urls text[]) +
--     foto canônica (primary_ref_url) — substitui o reference_image_url
--     singular sem quebrar dados antigos
--   • Tabela `projects` pra organizar gerações em "pastas"
--   • Tracking do prompt final pós-envelope + versão do template
--
-- Idempotente: pode rodar várias vezes.
-- ════════════════════════════════════════════════════════════════

BEGIN;

-- ─── projects (nova tabela) ───
CREATE TABLE IF NOT EXISTS projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    cover_url   TEXT,
    archived    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_user
    ON projects (user_id, created_at DESC)
    WHERE archived = false;


-- ─── personas: bundle de imagens ───
ALTER TABLE personas
    ADD COLUMN IF NOT EXISTS ref_image_urls   TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS primary_ref_url  TEXT,
    ADD COLUMN IF NOT EXISTS gender           TEXT,
    ADD COLUMN IF NOT EXISTS ethnicity        TEXT,
    ADD COLUMN IF NOT EXISTS age_range        TEXT;

-- Backfill: se persona antiga tem reference_image_url mas array vazio,
-- popula array com a única ref + define como primary_ref_url
UPDATE personas
   SET ref_image_urls  = ARRAY[reference_image_url],
       primary_ref_url = reference_image_url
 WHERE reference_image_url IS NOT NULL
   AND (ref_image_urls IS NULL OR cardinality(ref_image_urls) = 0);


-- ─── generations: discriminador tool/op + versioning + envelopes ───
ALTER TABLE generations
    ADD COLUMN IF NOT EXISTS tool              TEXT NOT NULL DEFAULT 'image',
    ADD COLUMN IF NOT EXISTS op                TEXT,
    ADD COLUMN IF NOT EXISTS model             TEXT,
    ADD COLUMN IF NOT EXISTS freepik_endpoint  TEXT,
    ADD COLUMN IF NOT EXISTS parent_id         UUID REFERENCES generations(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS project_id        UUID REFERENCES projects(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS refs              JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS envelope_version  TEXT,
    ADD COLUMN IF NOT EXISTS raw_prompt        TEXT,
    ADD COLUMN IF NOT EXISTS final_prompt      TEXT,
    ADD COLUMN IF NOT EXISTS attempt           INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS tags              TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS error_message     TEXT;

-- Constraint do `tool` — só vale dentro do enum suportado
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'generations_tool_check'
    ) THEN
        ALTER TABLE generations
            ADD CONSTRAINT generations_tool_check
            CHECK (tool IN (
                'image','video','edit','upscale','audio',
                'character','cinema','marketing',
                'ecommerce','product','r3d','assets','depth'
            ));
    END IF;
END $$;

-- Backfill: gerações antigas (pré-002) já tem media_type. Sincroniza tool.
UPDATE generations
   SET tool = CASE WHEN media_type = 'video' THEN 'video' ELSE 'image' END
 WHERE tool = 'image' AND media_type = 'video';

-- Índices novos
CREATE INDEX IF NOT EXISTS idx_generations_tool
    ON generations (tool, op, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generations_parent
    ON generations (parent_id)
    WHERE parent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_generations_project
    ON generations (project_id, created_at DESC)
    WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_generations_user_tool_created
    ON generations (user_id, tool, created_at DESC);


-- ─── RLS pra projects ───
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "users_own_projects" ON projects;
CREATE POLICY "users_own_projects" ON projects
    FOR ALL TO authenticated
    USING (auth.uid() = user_id);


-- ─── Helper view: árvore de re-rolls ───
-- Útil pro front exibir "geração X tem 3 versões" sem N+1 query.
CREATE OR REPLACE VIEW v_generation_versions AS
SELECT
    COALESCE(g.parent_id, g.id) AS root_id,
    g.id,
    g.user_id,
    g.tool,
    g.op,
    g.model,
    g.status,
    g.attempt,
    g.image_urls,
    g.video_urls,
    g.created_at
FROM generations g
ORDER BY COALESCE(g.parent_id, g.id), g.attempt;


COMMIT;
