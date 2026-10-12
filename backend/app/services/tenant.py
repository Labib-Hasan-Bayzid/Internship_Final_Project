from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AuditLog, Membership, Organization, User, UsagePeriod

PLANS = {
    "FREE": {"verification_runs": 50, "ai_explanations": 25, "projects": 3},
    "TEAM": {"verification_runs": 1000, "ai_explanations": 2000, "projects": 25},
    "BUSINESS": {"verification_runs": 10000, "ai_explanations": 20000, "projects": 100},
    "ENTERPRISE": {"verification_runs": -1, "ai_explanations": -1, "projects": -1},
}


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _resolve_user(db: Session, actor_email: str | None) -> User:
    settings = get_settings()
    email = (actor_email or settings.dev_identity_email).strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "A valid actor email is required")
    user = db.scalar(select(User).where(User.email.ilike(email)))
    if not user:
        user = User(
            email=email,
            name=settings.dev_identity_name if email == settings.dev_identity_email.lower() else email.split("@", 1)[0].replace(".", " ").title(),
        )
        db.add(user)
        db.flush()
    return user


def actor_user(
    db: Session = Depends(get_db),
    actor_email: str | None = Header(default=None, alias="X-Dcv-Actor-Email"),
) -> User:
    return _resolve_user(db, actor_email)


def actor_context(
    db: Session = Depends(get_db),
    organization_id: str | None = Header(default=None, alias="X-Dcv-Organization-Id"),
    actor_email: str | None = Header(default=None, alias="X-Dcv-Actor-Email"),
):
    """Resolve the canonical organization for the current actor.

    The packaged local environment uses an explicit dev identity. Public deployments
    must replace this header-based identity layer with the product's real identity
    provider; that authentication hardening is intentionally outside this release.
    """
    settings = get_settings()
    user = _resolve_user(db, actor_email)

    membership = None
    org = None
    if organization_id:
        requested_org = db.get(Organization, organization_id)
        if requested_org is not None:
            membership = db.scalar(
                select(Membership).where(
                    Membership.organization_id == requested_org.id,
                    Membership.user_id == user.id,
                    Membership.status == "ACTIVE",
                )
            )
            if membership is None:
                raise HTTPException(403, "User is not a member of this organization")
            if requested_org.status != "ACTIVE":
                raise HTTPException(403, "Organization is not active")
            org = requested_org

    if org is None:
        membership = db.scalar(
            select(Membership)
            .join(Organization, Membership.organization_id == Organization.id)
            .where(
                Membership.user_id == user.id,
                Membership.status == "ACTIVE",
                Organization.status == "ACTIVE",
            )
            .order_by(Organization.created_at.asc())
            .limit(1)
        )
        if membership:
            org = db.get(Organization, membership.organization_id)

    if org is None and settings.dev_identity_bootstrap:
        org = db.scalar(select(Organization).where(Organization.slug == settings.default_org_slug, Organization.status == "ACTIVE").limit(1))
        if org is None:
            raise HTTPException(500, "No active organization is configured")
        membership = db.scalar(
            select(Membership).where(
                Membership.organization_id == org.id,
                Membership.user_id == user.id,
                Membership.status == "ACTIVE",
            )
        )
        if membership is None:
            membership = Membership(organization_id=org.id, user_id=user.id, role="OWNER", status="ACTIVE")
            db.add(membership)
            db.commit()
            db.refresh(membership)

    if not org or not membership:
        raise HTTPException(403, "User is not a member of an active organization")
    return user, org, membership


def require_roles(context, *roles: str):
    user, org, membership = context
    if membership.status != "ACTIVE":
        raise HTTPException(403, "Membership is not active")
    if membership.role not in set(roles):
        raise HTTPException(403, f"Required organization role: {', '.join(roles)}")
    return user, org, membership


def require_member(context):
    return require_roles(context, "OWNER", "ADMIN", "MEMBER")


def require_admin(context):
    return require_roles(context, "OWNER", "ADMIN")


def ensure_usage(db: Session, org_id: str) -> UsagePeriod:
    period = month_start()
    row = db.scalar(
        select(UsagePeriod)
        .where(UsagePeriod.organization_id == org_id, UsagePeriod.period_start == period)
        .with_for_update()
    )
    if row:
        return row
    stmt = insert(UsagePeriod).values(organization_id=org_id, period_start=period).on_conflict_do_nothing(
        index_elements=[UsagePeriod.organization_id, UsagePeriod.period_start]
    )
    db.execute(stmt)
    row = db.scalar(
        select(UsagePeriod)
        .where(UsagePeriod.organization_id == org_id, UsagePeriod.period_start == period)
        .with_for_update()
    )
    if not row:
        raise RuntimeError("Unable to initialize organization usage period")
    return row


def check_entitlement(db: Session, org: Organization, metric: str, increment: int = 1):
    if increment < 0:
        raise ValueError("Entitlement increments must be non-negative")
    locked_org = db.scalar(select(Organization).where(Organization.id == org.id).with_for_update())
    if not locked_org or locked_org.status != "ACTIVE":
        raise HTTPException(403, "Organization is not active")
    limits = PLANS.get(locked_org.plan_code, PLANS["FREE"])
    if metric not in limits:
        raise HTTPException(500, f"Unknown entitlement metric: {metric}")
    limit = limits[metric]
    if limit < 0:
        return
    usage = ensure_usage(db, locked_org.id)
    current = int(getattr(usage, metric))
    if current + increment > limit:
        raise HTTPException(402, f"{metric.replace('_', ' ')} limit reached for {locked_org.plan_code} plan")
    setattr(usage, metric, current + increment)
    db.flush()


def audit(
    db: Session,
    org_id: str,
    actor_id: str | None,
    event_type: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
):
    db.add(
        AuditLog(
            organization_id=org_id,
            actor_user_id=actor_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
    )
