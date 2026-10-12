from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import BillingEvent, Organization, Subscription, UsagePeriod
from app.schemas import BillingOut, CheckoutIn
from app.services.billing import configured, create_checkout, create_portal, handle_webhook
from app.services.tenant import PLANS, actor_context, audit, ensure_usage, require_admin

router = APIRouter()


@router.get("/plans")
def plans():
    s = get_settings()
    return {
        "plans": [
            {"code": "FREE", "name": "Free", "limits": PLANS["FREE"]},
            {"code": "TEAM", "name": "Team", "limits": PLANS["TEAM"], "stripe_price_configured": bool(s.stripe_price_team)},
            {"code": "BUSINESS", "name": "Business", "limits": PLANS["BUSINESS"], "stripe_price_configured": bool(s.stripe_price_business)},
            {"code": "ENTERPRISE", "name": "Enterprise", "limits": PLANS["ENTERPRISE"], "contact_sales": True},
        ],
        "stripe_configured": configured(),
    }


@router.get("", response_model=BillingOut)
def billing(db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = context
    sub = db.get(Subscription, org.id)
    usage = db.scalar(select(UsagePeriod).where(UsagePeriod.organization_id == org.id).order_by(UsagePeriod.period_start.desc()).limit(1))
    return BillingOut(
        organization_id=org.id,
        plan_code=org.plan_code,
        subscription_status=sub.status if sub else "inactive",
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=sub.stripe_subscription_id if sub else None,
        cancel_at_period_end=bool(sub.cancel_at_period_end) if sub else False,
        current_period_end=sub.current_period_end if sub else None,
        usage={"verification_runs": usage.verification_runs if usage else 0, "ai_explanations": usage.ai_explanations if usage else 0},
        limits=PLANS.get(org.plan_code, PLANS["FREE"]),
    )


@router.post("/checkout")
def checkout(payload: CheckoutIn, db: Session = Depends(get_db), context=Depends(actor_context)):
    user, org, _ = require_admin(context)
    try:
        url = create_checkout(db, org, payload.plan, user.email)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Stripe checkout creation failed: {type(exc).__name__}: {exc}")
    audit(db, org.id, user.id, "billing.checkout_created", "organization", org.id, {"plan": payload.plan})
    db.commit()
    return {"url": url}


@router.post("/portal")
def portal(db: Session = Depends(get_db), context=Depends(actor_context)):
    user, org, _ = require_admin(context)
    try:
        url = create_portal(org)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Stripe portal creation failed: {type(exc).__name__}: {exc}")
    audit(db, org.id, user.id, "billing.portal_opened", "organization", org.id)
    db.commit()
    return {"url": url}


@router.post("/events/{event_id}/retry")
def retry_event(event_id: str, db: Session = Depends(get_db), context=Depends(actor_context)):
    user, org, _ = require_admin(context)
    event = db.scalar(select(BillingEvent).where(BillingEvent.id == event_id, BillingEvent.organization_id == org.id).with_for_update())
    if not event:
        raise HTTPException(404, "Billing event not found")
    if event.status == "PROCESSED":
        return {"ok": True, "status": event.status, "event_id": event.id, "message": "Event is already processed"}
    event.status = "FAILED"
    event.attempts = 0
    event.next_attempt_at = None
    event.error = None
    event.updated_at = datetime.now(timezone.utc)
    audit(db, org.id, user.id, "billing.event_retry_requested", "billing_event", event.id)
    db.commit()
    return {"ok": True, "status": event.status, "event_id": event.id, "message": "Event queued for replay"}


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, stripe_signature: str = Header(default="", alias="Stripe-Signature"), db: Session = Depends(get_db)):
    body = await request.body()
    try:
        return handle_webhook(db, body, str(stripe_signature))
    except HTTPException:
        raise
    except Exception as exc:
        # 4xx tells Stripe the payload/signature is invalid; 5xx asks Stripe to retry
        # a valid event whose local processing failed.
        from stripe.error import SignatureVerificationError

        if isinstance(exc, SignatureVerificationError) or "SignatureVerificationError" in type(exc).__name__:
            raise HTTPException(400, f"Stripe webhook rejected: {type(exc).__name__}")
        raise HTTPException(500, "Stripe webhook processing failed; retry will be accepted")
