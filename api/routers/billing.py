"""Billing — Stripe checkout + webhook.

Estrutura de pricing (Cubo / Refine):
  Planos mensais  : Starter R$27 / Creator R$59 / Pro R$129 / Studio R$799
  Planos anuais   : -30% sobre 12× mensal + bônus boas-vindas (pago à vista)
  Top-up packs    : Boost 3k / 8k / 25k / 80k
  Add-ons one-shot: Kling V3 +áudio, Veo 4K +áudio, Magnific 8K, LoRA, Voice Clone

Pesos de crédito por modelo seguem multiplicador ×1.785 sobre custo USD Freepik
(NB2 1K = 75 cred, igual à plataforma web Freepik).
"""
from __future__ import annotations

import os
from typing import Literal

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser

router = APIRouter(prefix="/billing", tags=["billing"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_URL = os.environ.get("APP_URL", "https://app.refinecubo.com.br")


# ════════════════════════════════════════════════════════════════
#                         PLANOS MENSAIS / ANUAIS
# ════════════════════════════════════════════════════════════════

TIER_PRICES = {
    # ─── Mensais ───
    "starter_monthly": {
        "price_id": os.environ.get("STRIPE_PRICE_STARTER_MONTHLY", ""),
        "credits": 10000, "amount_brl": 27, "interval": "month",
        "tier": "starter",
    },
    "creator_monthly": {
        "price_id": os.environ.get("STRIPE_PRICE_CREATOR_MONTHLY", ""),
        "credits": 25000, "amount_brl": 59, "interval": "month",
        "tier": "creator",
    },
    "pro_monthly": {
        "price_id": os.environ.get("STRIPE_PRICE_PRO_MONTHLY", ""),
        "credits": 60000, "amount_brl": 129, "interval": "month",
        "tier": "pro",
    },
    "studio_monthly": {
        "price_id": os.environ.get("STRIPE_PRICE_STUDIO_MONTHLY", ""),
        "credits": 380000, "amount_brl": 799, "interval": "month",
        "tier": "studio",
    },

    # ─── Anuais (-30% + bônus boas-vindas) ───
    "starter_yearly": {
        "price_id": os.environ.get("STRIPE_PRICE_STARTER_YEARLY", ""),
        "credits": 10000, "amount_brl": 227, "interval": "year",
        "tier": "starter", "welcome_bonus": 5000,
    },
    "creator_yearly": {
        "price_id": os.environ.get("STRIPE_PRICE_CREATOR_YEARLY", ""),
        "credits": 25000, "amount_brl": 496, "interval": "year",
        "tier": "creator", "welcome_bonus": 12000,
    },
    "pro_yearly": {
        "price_id": os.environ.get("STRIPE_PRICE_PRO_YEARLY", ""),
        "credits": 60000, "amount_brl": 1084, "interval": "year",
        "tier": "pro", "welcome_bonus": 30000,
    },
    "studio_yearly": {
        "price_id": os.environ.get("STRIPE_PRICE_STUDIO_YEARLY", ""),
        "credits": 380000, "amount_brl": 6712, "interval": "year",
        "tier": "studio", "welcome_bonus": 200000,
    },
}


# ════════════════════════════════════════════════════════════════
#                         TOP-UP PACKS (BOOSTS)
# ════════════════════════════════════════════════════════════════

CREDIT_PACKS = {
    "boost_3k":  {"price_id": os.environ.get("STRIPE_PRICE_BOOST_3K", ""),  "credits": 3000,  "amount_brl": 19},
    "boost_8k":  {"price_id": os.environ.get("STRIPE_PRICE_BOOST_8K", ""),  "credits": 8000,  "amount_brl": 39},
    "boost_25k": {"price_id": os.environ.get("STRIPE_PRICE_BOOST_25K", ""), "credits": 25000, "amount_brl": 99},
    "boost_80k": {"price_id": os.environ.get("STRIPE_PRICE_BOOST_80K", ""), "credits": 80000, "amount_brl": 279},
}


# ════════════════════════════════════════════════════════════════
#                     ADD-ONS ONE-SHOT (não-créditos)
# ════════════════════════════════════════════════════════════════

ADDONS = {
    "kling_v3_pro_10s_audio": {
        "price_id": os.environ.get("STRIPE_PRICE_ADDON_KLING_V3_PRO_AUDIO", ""),
        "amount_brl": 24.90,
        "label": "Vídeo Kling V3 Pro 10s com áudio",
    },
    "veo_4k_audio": {
        "price_id": os.environ.get("STRIPE_PRICE_ADDON_VEO_4K_AUDIO", ""),
        "amount_brl": 24.90,
        "label": "Vídeo Veo 3.1 4K 5s com áudio",
    },
    "magnific_8k": {
        "price_id": os.environ.get("STRIPE_PRICE_ADDON_MAGNIFIC_8K", ""),
        "amount_brl": 19.90,
        "label": "Upscale Magnific 4K → 8K",
    },
    "lora_medium": {
        "price_id": os.environ.get("STRIPE_PRICE_ADDON_LORA_MEDIUM", ""),
        "amount_brl": 199.00,
        "label": "Treino LoRA Medium (sua persona)",
    },
    "lora_ultra": {
        "price_id": os.environ.get("STRIPE_PRICE_ADDON_LORA_ULTRA", ""),
        "amount_brl": 349.00,
        "label": "Treino LoRA Ultra (alta fidelidade)",
    },
    "voice_clone": {
        "price_id": os.environ.get("STRIPE_PRICE_ADDON_VOICE_CLONE", ""),
        "amount_brl": 39.00,
        "label": "Voice Clone (cadastro de voz personalizada)",
    },
}


# ════════════════════════════════════════════════════════════════
#                            ENDPOINTS
# ════════════════════════════════════════════════════════════════

class CheckoutReq(BaseModel):
    tier: Literal[
        "starter_monthly", "creator_monthly", "pro_monthly", "studio_monthly",
        "starter_yearly",  "creator_yearly",  "pro_yearly",  "studio_yearly",
    ] | None = None
    pack: Literal["boost_3k", "boost_8k", "boost_25k", "boost_80k"] | None = None
    addon: Literal[
        "kling_v3_pro_10s_audio", "veo_4k_audio", "magnific_8k",
        "lora_medium", "lora_ultra", "voice_clone",
    ] | None = None


@router.post("/checkout")
def create_checkout(payload: CheckoutReq, user: AuthUser = Depends(get_current_user)) -> dict:
    if not stripe.api_key:
        raise HTTPException(503, "Stripe não configurado")

    if payload.tier:
        cfg = TIER_PRICES[payload.tier]
        mode = "subscription"
        meta = {
            "user_id": user.user_id, "tier_key": payload.tier,
            "tier": cfg["tier"], "interval": cfg["interval"],
            "credits": str(cfg["credits"]),
            "welcome_bonus": str(cfg.get("welcome_bonus", 0)),
        }
    elif payload.pack:
        cfg = CREDIT_PACKS[payload.pack]
        mode = "payment"
        meta = {"user_id": user.user_id, "pack": payload.pack, "credits": str(cfg["credits"])}
    elif payload.addon:
        cfg = ADDONS[payload.addon]
        mode = "payment"
        meta = {"user_id": user.user_id, "addon": payload.addon, "label": cfg["label"]}
    else:
        raise HTTPException(400, "tier, pack ou addon obrigatório")

    if not cfg["price_id"]:
        ident = payload.tier or payload.pack or payload.addon
        raise HTTPException(503, f"Stripe price ID não configurado pra {ident}")

    session = stripe.checkout.Session.create(
        client_reference_id=user.user_id,
        customer_email=user.email or None,
        line_items=[{"price": cfg["price_id"], "quantity": 1}],
        mode=mode,
        success_url=f"{APP_URL}/app/billing?success=1",
        cancel_url=f"{APP_URL}/app/billing?canceled=1",
        metadata=meta,
        subscription_data={"metadata": meta} if mode == "subscription" else None,
    )
    return {"url": session.url, "session_id": session.id}


@router.get("/portal")
def billing_portal(user: AuthUser = Depends(get_current_user)) -> dict:
    """Stripe Customer Portal — gerenciar assinatura."""
    if not stripe.api_key:
        raise HTTPException(503)
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT stripe_customer_id FROM profiles WHERE id=:u"
        ), {"u": user.user_id}).first()
    if not r or not r.stripe_customer_id:
        raise HTTPException(400, "Sem assinatura ativa")
    sess = stripe.billing_portal.Session.create(
        customer=r.stripe_customer_id, return_url=f"{APP_URL}/app/billing",
    )
    return {"url": sess.url}


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict:
    """Recebe eventos Stripe → atualiza tier/credits/anuais."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(400, f"Invalid webhook: {e}")

    et = event["type"]
    obj = event["data"]["object"]

    # ─── Checkout concluído (atualiza tier/customer apenas) ───
    # Os créditos do plano são adicionados em invoice.paid (que dispara
    # tanto no primeiro pagamento quanto nas renovações), pra evitar duplo crédito.
    if et == "checkout.session.completed":
        meta = obj.get("metadata", {}) or {}
        user_id = obj.get("client_reference_id") or meta.get("user_id")
        customer_id = obj.get("customer", "")
        if not user_id:
            return {"received": True}

        # Assinatura — atualiza tier e customer_id (créditos vêm em invoice.paid)
        if "tier_key" in meta:
            tier_key = meta["tier_key"]
            cfg = TIER_PRICES.get(tier_key, {})
            tier = cfg.get("tier", "")
            interval = cfg.get("interval", "month")

            with _engine.begin() as conn:
                conn.execute(text("""
                    UPDATE profiles
                       SET tier = :t,
                           subscription_interval = :iv,
                           subscription_tier_key = :tk,
                           stripe_customer_id = :cid
                     WHERE id = :u
                """), {
                    "t": tier, "iv": interval, "tk": tier_key,
                    "cid": customer_id, "u": user_id,
                })

        # Top-up pack — credita imediatamente
        elif "pack" in meta:
            credits = int(meta.get("credits", 0))
            with _engine.begin() as conn:
                conn.execute(text(
                    "UPDATE profiles SET credits = credits + :c, stripe_customer_id = :cid WHERE id = :u"
                ), {"c": credits, "cid": customer_id, "u": user_id})

        # Add-on one-shot — registra compra
        elif "addon" in meta:
            with _engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO addon_purchases (user_id, addon_id, amount_brl, stripe_session_id)
                    VALUES (:u, :a, :v, :s)
                """), {
                    "u": user_id, "a": meta["addon"],
                    "v": ADDONS.get(meta["addon"], {}).get("amount_brl", 0),
                    "s": obj.get("id", ""),
                })

    # ─── Renovação automática (mensal e anual via Stripe recurring) ───
    # Mensais : libera credits a cada invoice.paid (todo mês)
    # Anuais  : libera credits × 12 + welcome_bonus a cada invoice.paid (todo ano)
    # `billing_reason` distingue 1º pagamento ("subscription_create") de renovação ("subscription_cycle")
    elif et == "invoice.paid":
        sub_id = obj.get("subscription")
        if not sub_id:
            return {"received": True}

        sub = stripe.Subscription.retrieve(sub_id)
        sub_meta = sub.get("metadata", {}) or {}
        tier_key = sub_meta.get("tier_key", "")
        user_id = sub_meta.get("user_id", "")
        cfg = TIER_PRICES.get(tier_key, {})
        if not user_id or not cfg:
            return {"received": True}

        billing_reason = obj.get("billing_reason", "")
        is_first_payment = billing_reason == "subscription_create"
        interval = cfg.get("interval", "month")
        credits = cfg.get("credits", 0)
        welcome_bonus = cfg.get("welcome_bonus", 0)

        # Quanto creditar nesta cobrança:
        # - Mensal       : credits × 1 a cada mês
        # - Anual        : credits × 12 a cada ano (pacote fechado)
        # - Welcome bonus: só no primeiro pagamento (mensal e anual)
        multiplier = 12 if interval == "year" else 1
        amount_to_credit = credits * multiplier
        if is_first_payment:
            amount_to_credit += welcome_bonus

        with _engine.begin() as conn:
            conn.execute(text(
                "UPDATE profiles SET credits = credits + :c WHERE id = :u"
            ), {"c": amount_to_credit, "u": user_id})

    elif et == "customer.subscription.deleted":
        customer_id = obj.get("customer")
        if customer_id:
            with _engine.begin() as conn:
                conn.execute(text(
                    "UPDATE profiles SET tier='free', subscription_interval=NULL, subscription_tier_key=NULL "
                    "WHERE stripe_customer_id=:cid"
                ), {"cid": customer_id})

    return {"received": True}


@router.get("/me")
def my_billing(user: AuthUser = Depends(get_current_user)) -> dict:
    """Dados de billing pra UI de planos."""
    return {
        "tier": user.tier,
        "credits": user.credits,
        "tiers": {
            k: {
                "credits": v["credits"],
                "amount_brl": v["amount_brl"],
                "interval": v["interval"],
                "tier": v["tier"],
                "welcome_bonus": v.get("welcome_bonus", 0),
            }
            for k, v in TIER_PRICES.items()
        },
        "packs":  {k: {"credits": v["credits"], "amount_brl": v["amount_brl"]}
                   for k, v in CREDIT_PACKS.items()},
        "addons": {k: {"amount_brl": v["amount_brl"], "label": v["label"]}
                   for k, v in ADDONS.items()},
    }
