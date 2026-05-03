# Migrations

SQL migrations pra Postgres (Supabase).

## Como aplicar

### Local
```bash
psql $DATABASE_URL -f api/migrations/001_pricing_rebalance.sql
```

### Supabase Dashboard
1. Abrir SQL Editor
2. Colar conteúdo do arquivo `.sql`
3. Run

### Via Supabase CLI
```bash
supabase db push
# ou para um arquivo específico:
psql $(supabase secrets get DATABASE_URL) -f api/migrations/001_pricing_rebalance.sql
```

## Histórico

| Arquivo | Data | Descrição |
|---|---|---|
| `001_pricing_rebalance.sql` | 2026-04-28 | Nova estrutura de planos (Starter R$27/Creator R$59/Pro R$129/Studio R$799 + anuais -30%); tabelas `daily_usage` e `addon_purchases`; colunas `subscription_interval` e `subscription_tier_key` em `profiles`. |
| `002_tool_routing.sql` | 2026-05-03 | Tool routing: discriminador `tool`/`op`/`model` + `parent_id`/`project_id`/`refs jsonb`/`envelope_version`/`raw_prompt`/`final_prompt`/`attempt`/`tags` em `generations`. Nova tabela `projects`. Persona vira bundle: `ref_image_urls text[]` + `primary_ref_url`. View `v_generation_versions`. |
