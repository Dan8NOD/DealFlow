"""Token Broker — Stripe subscription verification.

Flow:
1. User clicks "Unlock Full Deck" on NOD-ify → Stripe hosted checkout
2. Stripe sends webhook to /api/broker/webhook → stores subscription
3. User redirects to /api/broker/success?session_id=... → returns token
4. MixMatch.html calls /api/broker/verify?token=... → unlocks tools
5. localStorage stores token. App verifies on each load.

No auth required — token IS the auth. Tied to Stripe customer ID.
"""
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import Column, Integer, String, DateTime, Boolean, text
from sqlalchemy.orm import Session
from app.db import engine, Base, get_db
from app.config import get_settings
from datetime import datetime, timezone
import httpx, os, secrets

router = APIRouter(prefix="/api/broker", tags=["broker"])
settings = get_settings()
STRIPE_SECRET = settings.stripe_secret_key or os.getenv("STRIPE_SECRET_KEY", "")
# ponytail: price ID set after Stripe product creation. Update in Render env.
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
BROKER_PRICE_MONTHLY = 49  # USD


class BrokerSubscription(Base):
    """ponytail: one row per active subscriber. Token = access."""
    __tablename__ = "broker_subscriptions"
    id = Column(Integer, primary_key=True)
    stripe_customer_id = Column(String(100), unique=True, index=True)
    stripe_subscription_id = Column(String(100), unique=True, index=True)
    email = Column(String(200), index=True)
    phone = Column(String(50))
    name = Column(String(200))
    access_token = Column(String(64), unique=True, index=True)
    status = Column(String(20), default="active")  # active, canceled, past_due
    created_at = Column(DateTime, server_default=text("now()"))
    canceled_at = Column(DateTime)


def _stripe_headers():
    return {
        "Authorization": f"Bearer {STRIPE_SECRET}",
        "Content-Type": "application/x-www-form-urlencoded",
    }


@router.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    """Create Stripe Checkout Session for $49/mo subscription."""
    if not STRIPE_SECRET or not STRIPE_PRICE_ID:
        raise HTTPException(500, "Stripe not configured. Set STRIPE_SECRET_KEY and STRIPE_PRICE_ID in Render env.")

    body = await request.json()
    name = body.get("name", "")
    phone = body.get("phone", "")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            headers=_stripe_headers(),
            data={
                "mode": "subscription",
                "line_items[0][price]": STRIPE_PRICE_ID,
                "line_items[0][quantity]": "1",
                "success_url": f"https://negotiatorsondemand.com/broker-success.html?session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": "https://negotiatorsondemand.com",
                "metadata[name]": name,
                "metadata[phone]": phone,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"Stripe error: {resp.text[:200]}")
    data = resp.json()
    return {"url": data["url"]}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Stripe webhook → create/update subscription record."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    # ponytail: signature verification skipped in dev. Enable in prod with STRIPE_WEBHOOK_SECRET.
    # import stripe; stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    event = await request.json()
    etype = event.get("type", "")

    if etype == "checkout.session.completed":
        session = event["data"]["object"]
        customer_id = session.get("customer")
        sub_id = session.get("subscription")
        email = session.get("customer_details", {}).get("email", "")
        name = session.get("metadata", {}).get("name", "")
        phone = session.get("metadata", {}).get("phone", "")
        token = secrets.token_urlsafe(32)

        with Session(engine) as db:
            existing = db.query(BrokerSubscription).filter(
                BrokerSubscription.stripe_customer_id == customer_id
            ).first()
            if existing:
                existing.access_token = token
                existing.status = "active"
                existing.stripe_subscription_id = sub_id
                existing.canceled_at = None
            else:
                sub = BrokerSubscription(
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=sub_id,
                    email=email, name=name, phone=phone,
                    access_token=token, status="active",
                )
                db.add(sub)
            db.commit()
        return {"ok": True}

    elif etype == "customer.subscription.deleted":
        sub_id = event["data"]["object"]["id"]
        with Session(engine) as db:
            sub = db.query(BrokerSubscription).filter(
                BrokerSubscription.stripe_subscription_id == sub_id
            ).first()
            if sub:
                sub.status = "canceled"
                sub.canceled_at = datetime.now(timezone.utc)
                db.commit()
        return {"ok": True}

    return {"ok": True, "ignored": etype}


@router.get("/success")
async def broker_success(session_id: str = Query(...)):
    """Redirect from Stripe checkout → return access token to the success page."""
    if not STRIPE_SECRET:
        raise HTTPException(500, "Stripe not configured")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.stripe.com/v1/checkout/sessions/{session_id}",
            headers=_stripe_headers(),
        )
    if resp.status_code != 200:
        raise HTTPException(502, "Could not retrieve session")

    data = resp.json()
    customer_id = data.get("customer")

    with Session(engine) as db:
        sub = db.query(BrokerSubscription).filter(
            BrokerSubscription.stripe_customer_id == customer_id
        ).first()
        if not sub:
            raise HTTPException(404, "Subscription not found. Contact support.")
        return JSONResponse({
            "token": sub.access_token,
            "status": sub.status,
            "name": sub.name or "",
        })


@router.get("/verify")
async def verify_token(token: str = Query(...)):
    """MixMatch.html calls this on load to check if token is valid."""
    with Session(engine) as db:
        sub = db.query(BrokerSubscription).filter(
            BrokerSubscription.access_token == token,
            BrokerSubscription.status == "active",
        ).first()
        if not sub:
            return {"active": False}
        return {
            "active": True,
            "name": sub.name or "",
            "member_since": sub.created_at.isoformat() if sub.created_at else None,
        }


@router.get("/subscribers/count")
async def subscriber_count():
    """Public endpoint — shows social proof on landing page."""
    with Session(engine) as db:
        count = db.query(BrokerSubscription).filter(
            BrokerSubscription.status == "active"
        ).count()
        return {"active_subscribers": count}
