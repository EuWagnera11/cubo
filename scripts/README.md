# Scripts

Scripts utilitários do backend Cubo / Refine.

## `create_stripe_products.py`

Cria os 18 produtos+preços do catálogo no Stripe automaticamente.

### Uso

```bash
# Instalar dependência (se ainda não tem)
pip install stripe

# Setar a secret key do Stripe (NUNCA commit isso!)
# Linux/Mac:
export STRIPE_SECRET_KEY="sk_live_..."

# Windows PowerShell:
$env:STRIPE_SECRET_KEY="sk_live_..."

# Windows CMD:
set STRIPE_SECRET_KEY=sk_live_...

# Rodar
python scripts/create_stripe_products.py
```

### O que faz

1. Cria/atualiza 18 produtos no Stripe (4 mensais + 4 anuais + 4 boosts + 6 add-ons)
2. Imprime os 18 `price_ids` prontos pra colar no `.env`
3. Salva backup em `scripts/.stripe_price_ids.txt` (gitignored)

### Idempotente

Pode rodar quantas vezes quiser. Usa `lookup_key` em cada Price — se já existir, reutiliza.
Se um valor mudar (ex: você reajustou o preço), desativa o antigo e cria novo.

### Modo Test vs Live

O script detecta automaticamente:
- `sk_test_...` → modo Test 🧪 (sem confirmação)
- `sk_live_...` → modo Live 🔴 (pede confirmação `SIM` antes de prosseguir)

### Próximos passos depois de rodar

1. Cole os 18 `STRIPE_PRICE_*` no `.env` do servidor
2. Cria webhook no Stripe Dashboard (instruções no output do script)
3. Cole `STRIPE_WEBHOOK_SECRET` no `.env`
4. Restart o backend → checkout funciona
