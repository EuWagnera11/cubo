"""Billing — Stripe checkout + webhook."""
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

# Map tier → Stripe price ID + créditos mensais
TIER_PRICES = {
    "starter":    {"price_id": os.environ.get("STRIPE_PRICE_STARTER", ""),    "credits": 500,    "amount_brl": 47},
    "creator":    {"price_id": os.environ.get("STRIPE_PRICE_CREATOR", ""),    "credits": 2500,   "amount_brl": 147},
    "pro":        {"price_id": os.environ.get("STRIPE_PRICE_PRO", ""),        "credits": 7500,   "amount_brl": 297},
    "agency":     {"price_id": os.environ.get("STRIPE_PRICE_AGENCY", ""),     "credits": 25000,  "amount_brl": 697},
    "enterprise": {"price_id": os.environ.get("STRIPE_PRICE_ENTERPRISE", ""), "credits": 100000, "amount_brl": 0},  # custom
}

# Top-up packs (compra avulsa)
CREDIT_PACKS = {
    "500":   {"price_id": os.environ.get("STRIPE_PRICE_PACK_500", ""),   "credits": 500,   "amount_brl": 39},
    "2000":  {"price_id": os.environ.get("STRIPE_PRICE_PACK_2000", ""),  "credits": 2000,  "amount_brl": 129},
    "5000":  {"price_id": os.environ.get("STRIPE_PRICE_PACK_5000", ""),  "credits": 5000,  "amount_brl": 297},
    "15000": {"price_id": os.environ.get("STRIPE_PRICE_PACK_15000", ""), "credits": 15000, "amount_brl": 797},
}


class CheckoutReq(BaseModel):
    tier: Literal["starter", "creator", "pro", "agency", "enterprise"] | None = None
    pack: Literal["500", "2000", "5000", "15000"] | None = None


@router.post("/checkout")
def create_checkout(payload: CheckoutReq, user: AuthUser = Depends(get_current_user)) -> dict:
    if not stripe.api_key:
        raise HTTPException(503, "Stripe não configurado")

    if payload.tier:
        cfg = TIER_PRICES[payload.tier]
        mode = "subscription"
    elif payload.pack:
        cfg = CREDIT_PACKS[payload.pack]
        mode = "payment"
    else:
        raise HTTPException(400, "tier ou pack obrigatório")

    if not cfg["price_id"]:
        raise HTTPException(503, f"Stripe price ID não configurado pra {payload.tier or payload.pack}")

    session = stripe.checkout.Session.create(
        client_reference_id=user.user_id,
        customer_email=user.email or None,
        line_items=[{"price": cfg["price_id"], "quantity": 1}],
        mode=mode,
        success_url=f"{APP_URL}/app/billing?success=1",
        cancel_url=f"{APP_URL}/app/billing?canceled=1",
        metadata={
            "user_id": user.user_id,
            "tier": payload.tier or "",
            "pack": payload.pack or "",
            "credits": str(cfg["credits"]),
        },
    )
    return {"url": session.url, "session_id": session.id}


@router.get("/portal")
def billing_portal(user: AuthUser = Depends(get_current_user)) -> dict:
    """Stripe Customer Portal — gerenciar assinatura."""
    if not stripe.api_key:
        raise HTTPException(503)
    # Buscar customer_id
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
    """Recebe eventos Stripe → atualiza tier/credits."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(400, f"Invalid webhook: {e}")

    et = event["type"]
    obj = event["data"]["object"]

    if et == "checkout.session.completed":
        user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("user_id")
        tier = obj.get("metadata", {}).get("tier") or ""
        pack = obj.get("metadata", {}).get("pack") or ""
        credits = int(obj.get("metadata", {}).get("credits") or 0)
        customer_id = obj.get("customer", "")

        if user_id:
            with _engine.begin() as conn:
                if tier:
                    conn.execute(text("""
                        UPDATE profiles SET tier=:t, credits=credits+:c, stripe_customer_id=:cid
                        WHERE id=:u
                    """), {"t": tier, "c": credits, "cid": customer_id, "u": user_id})
                elif pack:
                    conn.execute(text(
                        "UPDATE profiles SET credits=credits+:c, stripe_customer_id=:cid WHERE id=:u"
                    ), {"c": credits, "cid": customer_id, "u": user_id})

    elif et == "invoice.paid":
        # renewal mensal: top up dos créditos
        sub_id = obj.get("subscription")
        if sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
            tier = sub.get("metadata", {}).get("tier", "")
            user_id = sub.get("metadata", {}).get("user_id", "")
            credits = TIER_PRICES.get(tier, {}).get("credits", 0)
            if user_id and credits:
                with _engine.begin() as conn:
                    conn.execute(text(
                        "UPDATE profiles SET credits=credits+:c WHERE id=:u"
                    ), {"c": credits, "u": user_id})

    elif et == "customer.subscription.deleted":
        # downgrade pra free
        customer_id = obj.get("customer")
        if customer_id:
            with _engine.begin() as conn:
                conn.execute(text(
                    "UPDATE profiles SET tier='free' WHERE stripe_customer_id=:cid"
                ), {"cid": customer_id})

    return {"received": True}


@router.get("/me")
def my_billing(user: AuthUser = Depends(get_current_user)) -> dict:
    return {
        "tier": user.tier,
        "credits": user.credits,
        "tiers": {k: {"credits": v["credits"], "amount_brl": v["amount_brl"]}
                  for k, v in TIER_PRICES.items()},
        "packs": {k: v for k, v in CREDIT_PACKS.items()},
    }
