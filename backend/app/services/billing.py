from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncio

from sqlalchemy import select, text

import stripe
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BillingEvent, Organization, Subscription
from app.services.tenant import PLANS


ACTIVE_SUBSCRIPTION_STATES = {"trialing", "active", "past_due", "incomplete"}


def configured() -> bool:
    return bool(get_settings().stripe_secret_key)


def _price_for_plan(plan: str) -> str | None:
    settings = get_settings()
    return {"TEAM": settings.stripe_price_team, "BUSINESS": settings.stripe_price_business}.get(plan)


def _plan_for_price(price_id: str | None) -> str | None:
    if not price_id:
        return None
    settings = get_settings()
    if price_id == settings.stripe_price_team:
        return "TEAM"
    if price_id == settings.stripe_price_business:
        return "BUSINESS"
    return None


def create_checkout(db: Session, org: Organization, plan: str, actor_email: str | None = None) -> str:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise RuntimeError("Stripe is not configured")
    if plan not in {"TEAM", "BUSINESS"}:
        raise RuntimeError("Checkout is only available for Team or Business")
    locked_org = db.scalar(select(Organization).where(Organization.id == org.id).with_for_update())
    if not locked_org:
        raise RuntimeError("Organization not found")
    existing = db.get(Subscription, locked_org.id)
    if existing and existing.stripe_subscription_id and existing.status in ACTIVE_SUBSCRIPTION_STATES:
        raise RuntimeError("Organization already has an active subscription; use the billing portal to change it")
    price = _price_for_plan(plan)
    if not price:
        raise RuntimeError(f"No Stripe price configured for {plan}")

    stripe.api_key = settings.stripe_secret_key
    customer_id = org.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            name=locked_org.name,
            email=locked_org.billing_email or actor_email,
            metadata={"dcv_org_id": locked_org.id},
        )
        customer_id = customer.id
        locked_org.stripe_customer_id = customer_id
        db.flush()

    success = settings.stripe_success_url or (settings.app_public_url.rstrip("/") + "/?billing=success")
    cancel = settings.stripe_cancel_url or (settings.app_public_url.rstrip("/") + "/?billing=cancel")
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price, "quantity": 1}],
        success_url=success,
        cancel_url=cancel,
        metadata={"dcv_org_id": locked_org.id, "dcv_plan": plan},
        subscription_data={"metadata": {"dcv_org_id": locked_org.id, "dcv_plan": plan}},
    )
    return session.url


def create_portal(org: Organization) -> str:
    settings = get_settings()
    if not settings.stripe_secret_key or not org.stripe_customer_id:
        raise RuntimeError("Stripe customer is not configured")
    stripe.api_key = settings.stripe_secret_key
    session = stripe.billing_portal.Session.create(
        customer=org.stripe_customer_id,
        return_url=settings.billing_portal_return_url or settings.app_public_url,
    )
    return session.url


def _resolve_org(db: Session, data: dict) -> Organization | None:
    metadata = data.get("metadata") or {}
    org_id = metadata.get("dcv_org_id")
    if org_id:
        org = db.get(Organization, org_id)
        if org:
            return org
    customer_id = data.get("customer")
    if customer_id:
        return db.scalar(select(Organization).where(Organization.stripe_customer_id == customer_id))
    return None


def _apply_event(db: Session, event: dict, record: BillingEvent) -> str | None:
    event_type = event["type"]
    data = (event.get("data") or {}).get("object") or {}
    org = _resolve_org(db, data)
    if not org:
        record.organization_id = None
        return None

    record.organization_id = org.id
    sub_row = db.get(Subscription, org.id)
    if not sub_row:
        sub_row = Subscription(organization_id=org.id, plan_code="FREE", status="inactive")
        db.add(sub_row)
        db.flush()

    created_epoch = event.get("created")
    event_created = datetime.fromtimestamp(int(created_epoch), timezone.utc) if created_epoch else datetime.now(timezone.utc)
    # Stripe may deliver events out of order. Ignore a stale event after recording it.
    if sub_row.last_stripe_event_created_at and event_created <= sub_row.last_stripe_event_created_at:
        return org.id

    if event_type == "checkout.session.completed":
        plan = (data.get("metadata") or {}).get("dcv_plan")
        if plan in {"TEAM", "BUSINESS"}:
            org.plan_code = plan
            sub_row.plan_code = plan
        sub_row.status = "active"
        sub_row.stripe_customer_id = data.get("customer") or org.stripe_customer_id
        sub_row.stripe_subscription_id = data.get("subscription")

    elif event_type.startswith("customer.subscription."):
        sub_row.stripe_customer_id = data.get("customer") or sub_row.stripe_customer_id
        sub_row.stripe_subscription_id = data.get("id") or sub_row.stripe_subscription_id
        price_id = ((data.get("items") or {}).get("data") or [{}])[0].get("price", {}).get("id")
        sub_row.stripe_price_id = price_id
        sub_row.status = data.get("status", "unknown")
        sub_row.cancel_at_period_end = bool(data.get("cancel_at_period_end"))
        period_end = data.get("current_period_end")
        sub_row.current_period_end = datetime.fromtimestamp(period_end, timezone.utc) if period_end else None
        plan = (data.get("metadata") or {}).get("dcv_plan") or _plan_for_price(price_id)
        if plan in PLANS:
            org.plan_code = plan
            sub_row.plan_code = plan
        if event_type == "customer.subscription.deleted":
            org.plan_code = "FREE"
            sub_row.plan_code = "FREE"
            sub_row.status = "canceled"

    elif event_type == "invoice.payment_failed":
        sub_row.status = "past_due"

    elif event_type == "invoice.paid":
        if sub_row.status == "past_due":
            sub_row.status = "active"

    # All recognized/ignored-newer events advance the watermark to prevent later stale events
    # from overwriting current subscription state.
    sub_row.last_stripe_event_created_at = event_created
    sub_row.updated_at = datetime.now(timezone.utc)
    org.updated_at = datetime.now(timezone.utc)
    return org.id

def handle_webhook(db: Session, raw_body: bytes, signature: str) -> dict:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise RuntimeError("Stripe webhook secret is not configured")
    event = stripe.Webhook.construct_event(raw_body, signature, settings.stripe_webhook_secret)
    payload = event.to_dict_recursive() if hasattr(event, "to_dict_recursive") else dict(event)
    event_id = event["id"]
    now = datetime.now(timezone.utc)

    existing = db.scalar(select(BillingEvent).where(BillingEvent.stripe_event_id == event_id).with_for_update())
    if existing and existing.status == "PROCESSED":
        return {"duplicate": True, "event_id": event_id, "type": existing.event_type, "organization_id": existing.organization_id}
    if existing:
        record = existing
        record.status = "PROCESSING"
        record.error = None
        record.next_attempt_at = None
        record.attempts = int(record.attempts or 0) + 1
        record.updated_at = now
    else:
        record = BillingEvent(
            stripe_event_id=event_id,
            event_type=event["type"],
            payload=payload,
            status="PROCESSING",
            attempts=1,
            updated_at=now,
        )
        db.add(record)
        try:
            db.flush()
        except Exception:
            db.rollback()
            record = db.scalar(select(BillingEvent).where(BillingEvent.stripe_event_id == event_id).with_for_update())
            if record and record.status == "PROCESSED":
                return {"duplicate": True, "event_id": event_id, "type": record.event_type, "organization_id": record.organization_id}
            if not record:
                raise
            record.status = "PROCESSING"
            record.attempts = int(record.attempts or 0) + 1
            record.updated_at = now
    db.flush()

    try:
        org_id = _apply_event(db, payload, record)
        record.status = "PROCESSED"
        record.processed_at = now
        record.error = None
        record.next_attempt_at = None
        record.updated_at = now
        db.commit()
        return {"duplicate": False, "event_id": event_id, "type": event["type"], "organization_id": org_id}
    except Exception as exc:
        db.rollback()
        failed = db.get(BillingEvent, record.id) if record.id else db.scalar(select(BillingEvent).where(BillingEvent.stripe_event_id == event_id))
        if failed:
            failed.status = "FAILED"
            failed.error = f"{type(exc).__name__}: {exc}"
            failed.next_attempt_at = datetime.now(timezone.utc)
            failed.updated_at = datetime.now(timezone.utc)
            db.commit()
        raise

async def billing_worker_loop() -> None:
    """Replay previously validated Stripe events that failed during local processing.

    Stripe itself retries non-2xx webhook deliveries, but a local replay queue makes
    recovery deterministic after transient database/provider failures and gives
    operators an explicit retry path without asking Stripe to resend the event.
    """
    from app.database import SessionLocal

    settings = get_settings()
    while True:
        db = SessionLocal()
        ids: list[str] = []
        try:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(minutes=settings.billing_stale_minutes)
            db.execute(
                text(
                    "UPDATE billing_events SET status='FAILED',next_attempt_at=NOW(),updated_at=NOW() "
                    "WHERE status='PROCESSING' AND updated_at<:cutoff AND attempts<:max_attempts"
                ),
                {"cutoff": cutoff, "max_attempts": settings.billing_max_attempts},
            )
            db.execute(
                text(
                    "UPDATE billing_events SET status='FAILED',next_attempt_at=NULL,updated_at=NOW(),"
                    "error=COALESCE(error,'Maximum attempts exceeded.') "
                    "WHERE status IN ('FAILED','PROCESSING') AND attempts>=:max_attempts"
                ),
                {"max_attempts": settings.billing_max_attempts},
            )
            events = db.scalars(
                select(BillingEvent)
                .where(BillingEvent.status == "FAILED")
                .where((BillingEvent.next_attempt_at.is_(None)) | (BillingEvent.next_attempt_at <= now))
                .where(BillingEvent.attempts < settings.billing_max_attempts)
                .order_by(BillingEvent.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(10)
            ).all()
            for record in events:
                record.status = "PROCESSING"
                record.attempts = int(record.attempts or 0) + 1
                record.error = None
                record.next_attempt_at = None
                record.updated_at = now
                ids.append(record.id)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

        for event_id in ids:
            db = SessionLocal()
            try:
                record = db.get(BillingEvent, event_id)
                if not record:
                    continue
                try:
                    _apply_event(db, record.payload, record)
                    record.status = "PROCESSED"
                    record.processed_at = datetime.now(timezone.utc)
                    record.error = None
                    record.next_attempt_at = None
                    record.updated_at = datetime.now(timezone.utc)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    failed = db.get(BillingEvent, event_id)
                    if failed:
                        failed.status = "FAILED"
                        failed.error = f"{type(exc).__name__}: {exc}"
                        if failed.attempts >= settings.billing_max_attempts:
                            failed.next_attempt_at = None
                        else:
                            delay = min(300, 2 ** max(int(failed.attempts) - 1, 0))
                            failed.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                        failed.updated_at = datetime.now(timezone.utc)
                        db.commit()
            finally:
                db.close()
        await asyncio.sleep(settings.billing_poll_seconds)

