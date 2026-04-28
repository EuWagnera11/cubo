"""
Cria os 18 produtos+preços do Cubo / Refine no Stripe automaticamente.

Uso:
    cd cubo-backend
    export STRIPE_SECRET_KEY="sk_live_..."     # Linux/Mac
    set STRIPE_SECRET_KEY=sk_live_...          # Windows CMD
    $env:STRIPE_SECRET_KEY="sk_live_..."       # Windows PowerShell

    python scripts/create_stripe_products.py

O que faz:
    - Cria 4 planos mensais  (Starter R$27, Creator R$59, Pro R$129, Studio R$799)
    - Cria 4 planos anuais   (-30% sobre 12× mensal)
    - Cria 4 packs Boost     (top-up avulso 3k/8k/25k/80k)
    - Cria 6 add-ons one-shot (Kling V3+áudio, Veo 4K+áudio, Magnific 8K, LoRA, Voice Clone)

Idempotente: usa `lookup_key` em cada Price. Se rodar de novo, NÃO duplica nada,
só atualiza o produto existente. Pode rodar várias vezes sem medo.

Output: imprime as 18 linhas prontas pra colar no .env do servidor:
    STRIPE_PRICE_STARTER_MONTHLY=price_1ABCxyz...
    STRIPE_PRICE_CREATOR_MONTHLY=price_1DEFxyz...
    ...
"""
from __future__ import annotations

import os
import sys
from typing import Optional

try:
    import stripe
except ImportError:
    print("ERRO: stripe lib não instalada.")
    print("Roda: pip install stripe")
    sys.exit(1)


# ─────────────── Config ───────────────

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
if not STRIPE_SECRET_KEY:
    print("ERRO: variável STRIPE_SECRET_KEY não definida.")
    print('Use: export STRIPE_SECRET_KEY="sk_live_..."  (Linux/Mac)')
    print('Ou:  $env:STRIPE_SECRET_KEY="sk_live_..."    (Windows PowerShell)')
    sys.exit(1)

if not STRIPE_SECRET_KEY.startswith("sk_"):
    print("ERRO: STRIPE_SECRET_KEY parece inválida (não começa com sk_).")
    print("É a SECRET key, não a publishable (pk_...).")
    sys.exit(1)

stripe.api_key = STRIPE_SECRET_KEY

IS_TEST = STRIPE_SECRET_KEY.startswith("sk_test_")
mode_label = "TEST 🧪" if IS_TEST else "LIVE 🔴"


# ─────────────── Catálogo de produtos ───────────────

# Cada item: (env_var_name, lookup_key, product_name, description, amount_cents, recurring_interval_or_None)
# amount_cents = preço × 100 (BRL em centavos)
# recurring_interval = "month", "year" ou None (one-time)

CATALOG = [
    # ═══ Planos Mensais ═══
    ("STRIPE_PRICE_STARTER_MONTHLY", "cubo_starter_monthly",
     "Cubo Starter (Mensal)", "10.000 créditos por mês",
     2700, "month"),
    ("STRIPE_PRICE_CREATOR_MONTHLY", "cubo_creator_monthly",
     "Cubo Creator (Mensal)", "25.000 créditos por mês",
     5900, "month"),
    ("STRIPE_PRICE_PRO_MONTHLY", "cubo_pro_monthly",
     "Cubo Pro (Mensal)", "60.000 créditos por mês",
     12900, "month"),
    ("STRIPE_PRICE_STUDIO_MONTHLY", "cubo_studio_monthly",
     "Cubo Studio (Mensal)", "380.000 créditos por mês",
     79900, "month"),

    # ═══ Planos Anuais (-30% + bônus boas-vindas) ═══
    ("STRIPE_PRICE_STARTER_YEARLY", "cubo_starter_yearly",
     "Cubo Starter (Anual)",
     "120.000 créditos liberados na hora + 5.000 bônus boas-vindas. Renovação anual.",
     22700, "year"),
    ("STRIPE_PRICE_CREATOR_YEARLY", "cubo_creator_yearly",
     "Cubo Creator (Anual)",
     "300.000 créditos liberados na hora + 12.000 bônus boas-vindas. Renovação anual.",
     49600, "year"),
    ("STRIPE_PRICE_PRO_YEARLY", "cubo_pro_yearly",
     "Cubo Pro (Anual)",
     "720.000 créditos liberados na hora + 30.000 bônus boas-vindas. Renovação anual.",
     108400, "year"),
    ("STRIPE_PRICE_STUDIO_YEARLY", "cubo_studio_yearly",
     "Cubo Studio (Anual)",
     "4.560.000 créditos liberados na hora + 200.000 bônus boas-vindas. Renovação anual.",
     671200, "year"),

    # ═══ Top-up Boost Packs (one-time) ═══
    ("STRIPE_PRICE_BOOST_3K", "cubo_boost_3k",
     "Boost 3.000 créditos", "Pacote avulso de 3.000 créditos. Não expira.",
     1900, None),
    ("STRIPE_PRICE_BOOST_8K", "cubo_boost_8k",
     "Boost 8.000 créditos", "Pacote avulso de 8.000 créditos. Não expira.",
     3900, None),
    ("STRIPE_PRICE_BOOST_25K", "cubo_boost_25k",
     "Boost 25.000 créditos", "Pacote avulso de 25.000 créditos. Não expira.",
     9900, None),
    ("STRIPE_PRICE_BOOST_80K", "cubo_boost_80k",
     "Boost 80.000 créditos", "Pacote avulso de 80.000 créditos. Não expira.",
     27900, None),

    # ═══ Add-ons One-shot ═══
    ("STRIPE_PRICE_ADDON_KLING_V3_PRO_AUDIO", "cubo_addon_kling_v3_pro_audio",
     "Vídeo Kling V3 Pro 10s + Áudio",
     "1 geração de vídeo Kling V3 Pro de 10 segundos com áudio sincronizado.",
     2490, None),
    ("STRIPE_PRICE_ADDON_VEO_4K_AUDIO", "cubo_addon_veo_4k_audio",
     "Vídeo Veo 3.1 4K 5s + Áudio",
     "1 geração de vídeo Veo 3.1 em 4K com áudio.",
     2490, None),
    ("STRIPE_PRICE_ADDON_MAGNIFIC_8K", "cubo_addon_magnific_8k",
     "Magnific Upscaler 4K → 8K",
     "1 upscale Magnific de 4K para 8K (ultra alta resolução).",
     1990, None),
    ("STRIPE_PRICE_ADDON_LORA_MEDIUM", "cubo_addon_lora_medium",
     "Treino LoRA Medium",
     "Treina uma LoRA personalizada com sua persona (qualidade Medium).",
     19900, None),
    ("STRIPE_PRICE_ADDON_LORA_ULTRA", "cubo_addon_lora_ultra",
     "Treino LoRA Ultra",
     "Treina uma LoRA personalizada com qualidade Ultra (alta fidelidade).",
     34900, None),
    ("STRIPE_PRICE_ADDON_VOICE_CLONE", "cubo_addon_voice_clone",
     "Voice Clone (cadastro de voz)",
     "Cadastre uma voz personalizada (sua ou de terceiro com permissão).",
     3900, None),
]


# ─────────────── Helpers ───────────────

def find_price_by_lookup_key(lookup_key: str) -> Optional[stripe.Price]:
    """Busca um Price ativo pelo lookup_key. None se não existir."""
    prices = stripe.Price.list(lookup_keys=[lookup_key], active=True, limit=1)
    return prices.data[0] if prices.data else None


def find_or_create_product(name: str, description: str) -> stripe.Product:
    """Procura produto pelo nome (metadata.cubo_name). Cria se não achar."""
    products = stripe.Product.search(query=f"metadata['cubo_name']:'{name}'")
    if products.data:
        product = products.data[0]
        # Atualiza descrição se mudou
        if product.description != description:
            product = stripe.Product.modify(product.id, description=description)
        return product

    return stripe.Product.create(
        name=name,
        description=description,
        metadata={"cubo_name": name, "managed_by": "cubo_pricing_script"},
    )


def create_price(
    *, lookup_key: str, product: stripe.Product,
    amount_cents: int, recurring_interval: Optional[str],
) -> stripe.Price:
    """Cria Price com lookup_key. Se já existe, retorna existente."""
    existing = find_price_by_lookup_key(lookup_key)
    if existing:
        # Verifica se valor/intervalo bateram
        same_amount = existing.unit_amount == amount_cents
        same_interval = (
            (existing.recurring is None and recurring_interval is None) or
            (existing.recurring is not None
             and existing.recurring.get("interval") == recurring_interval)
        )
        if same_amount and same_interval:
            return existing

        # Mudou alguma coisa → desativa o antigo e cria novo
        # (Stripe não permite editar amount/interval de Price existente)
        stripe.Price.modify(existing.id, active=False)

    params = {
        "product": product.id,
        "currency": "brl",
        "unit_amount": amount_cents,
        "lookup_key": lookup_key,
        "metadata": {"managed_by": "cubo_pricing_script"},
    }
    if recurring_interval:
        params["recurring"] = {"interval": recurring_interval}

    return stripe.Price.create(**params)


# ─────────────── Main ───────────────

def main():
    print(f"\n🔑 Conectado ao Stripe em modo: {mode_label}")
    if not IS_TEST:
        print("⚠️  ATENÇÃO: você está em LIVE mode. Produtos serão criados em produção.")
        confirm = input("Continuar? Digite SIM pra prosseguir: ").strip()
        if confirm != "SIM":
            print("Cancelado.")
            sys.exit(0)

    print(f"\n📦 Criando/atualizando {len(CATALOG)} produtos...\n")

    env_lines: list[str] = []
    summary: list[tuple[str, str]] = []

    for env_var, lookup_key, name, desc, amount, interval in CATALOG:
        product = find_or_create_product(name, desc)
        price = create_price(
            lookup_key=lookup_key, product=product,
            amount_cents=amount, recurring_interval=interval,
        )
        amount_brl = amount / 100
        kind = f"{interval}ly" if interval else "one-time"
        print(f"  ✓ {name:<45} {kind:<10} R${amount_brl:>8.2f}  →  {price.id}")
        env_lines.append(f"{env_var}={price.id}")
        summary.append((name, price.id))

    # ─── Output ───
    print("\n" + "=" * 70)
    print("📋 COLE NO .env DO SERVIDOR (Railway / Fly / VPS):")
    print("=" * 70 + "\n")
    for line in env_lines:
        print(line)

    print("\n" + "=" * 70)
    print("🎯 PRÓXIMO PASSO: criar o webhook no Stripe Dashboard")
    print("=" * 70)
    print("""
1. Acesse: https://dashboard.stripe.com/webhooks
2. Clique em "Add endpoint"
3. URL do endpoint: https://api.refinecubo.com.br/billing/webhook
   (ou onde seu backend roda em produção)
4. Eventos a escutar (selecione manualmente):
     ✓ checkout.session.completed
     ✓ invoice.paid
     ✓ customer.subscription.deleted
5. Copie o "Signing secret" (whsec_...) e adicione ao .env:
     STRIPE_WEBHOOK_SECRET=whsec_...
""")

    # Salva backup local em arquivo
    backup_path = "scripts/.stripe_price_ids.txt"
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(f"# Generated by create_stripe_products.py (mode: {mode_label})\n\n")
        for line in env_lines:
            f.write(line + "\n")
    print(f"💾 Backup salvo em: {backup_path}")
    print("⚠️  ESSE ARQUIVO ESTÁ NO .gitignore — NÃO commit ele.\n")


if __name__ == "__main__":
    main()
