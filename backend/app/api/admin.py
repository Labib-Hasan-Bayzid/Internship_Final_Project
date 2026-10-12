from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AuditLog, Invitation, Membership, Organization, Project, UsagePeriod, User
from app.schemas import (
    InviteCreate,
    InviteOut,
    MemberOut,
    MemberRoleUpdate,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
    UsageOut,
)
from app.services.tenant import PLANS, actor_context, actor_user, audit, ensure_usage, require_admin

router = APIRouter()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _member_out(db: Session, membership: Membership) -> MemberOut:
    user = db.get(User, membership.user_id)
    if not user:
        raise HTTPException(500, "Membership references a missing user")
    return MemberOut(
        membership_id=membership.id,
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=membership.role,
        status=membership.status,
        created_at=membership.created_at,
    )


@router.get("/context")
def context(
    db: Session = Depends(get_db),
    user: User = Depends(actor_user),
    organization_id: str | None = Header(default=None, alias="X-Dcv-Organization-Id"),
):
    rows = db.execute(
        select(Membership, Organization)
        .join(Organization, Membership.organization_id == Organization.id)
        .where(
            Membership.user_id == user.id,
            Membership.status == "ACTIVE",
            Organization.status == "ACTIVE",
        )
        .order_by(Organization.created_at.asc())
    ).all()
    current = None
    if organization_id:
        for membership, org in rows:
            if org.id == organization_id:
                current = (membership, org)
                break
        if current is None:
            raise HTTPException(403, "User is not a member of this organization")
    elif rows:
        current = rows[0]
    membership, org = current if current else (None, None)
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "current": {"organization_id": org.id if org else None, "role": membership.role if membership else None},
        "organizations": [
            {"id": m.organization_id, "name": o.name, "slug": o.slug, "plan_code": o.plan_code, "role": m.role}
            for m, o in rows
        ],
    }


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
def create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(actor_user),
):
    name = payload.name.strip()
    slug = payload.slug.strip().lower()
    if db.scalar(select(Organization).where(func.lower(Organization.slug) == slug.lower())):
        raise HTTPException(409, "Organization slug already exists")
    if db.scalar(select(Organization).where(func.lower(Organization.name) == name.lower())):
        raise HTTPException(409, "Organization name already exists")
    org = Organization(name=name, slug=slug)
    db.add(org)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role="OWNER", status="ACTIVE"))
    audit(db, org.id, user.id, "organization.created", "organization", org.id, {"name": name, "slug": slug})
    db.commit()
    db.refresh(org)
    return org


@router.get("/organization", response_model=OrganizationOut)
def get_org(db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = context
    return org


@router.patch("/organization", response_model=OrganizationOut)
def update_org(
    payload: OrganizationUpdate,
    db: Session = Depends(get_db),
    context=Depends(actor_context),
):
    user, org, _ = require_admin(context)
    name = payload.name.strip()
    duplicate = db.scalar(
        select(Organization).where(func.lower(Organization.name) == name.lower(), Organization.id != org.id)
    )
    if duplicate:
        raise HTTPException(409, "Organization name already exists")
    org.name = name
    org.billing_email = payload.billing_email.strip() if payload.billing_email else None
    org.updated_at = utcnow()
    audit(db, org.id, user.id, "organization.updated", "organization", org.id, payload.model_dump())
    db.commit()
    db.refresh(org)
    return org


@router.get("/members", response_model=list[MemberOut])
def members(db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = require_admin(context)
    rows = db.scalars(
        select(Membership)
        .where(Membership.organization_id == org.id)
        .order_by(Membership.created_at.asc())
    ).all()
    return [_member_out(db, m) for m in rows]


@router.patch("/members/{membership_id}", response_model=MemberOut)
def update_member(
    membership_id: str,
    payload: MemberRoleUpdate,
    db: Session = Depends(get_db),
    context=Depends(actor_context),
):
    actor, org, actor_membership = require_admin(context)
    membership = db.scalar(
        select(Membership)
        .where(Membership.id == membership_id, Membership.organization_id == org.id)
        .with_for_update()
    )
    if not membership:
        raise HTTPException(404, "Member not found")

    # Administrators can manage non-owner members; only an owner can change an owner.
    if membership.role == "OWNER" and actor_membership.role != "OWNER":
        raise HTTPException(403, "Only an owner can manage another owner")
    if membership.role == "OWNER" and payload.role != "OWNER" and actor_membership.role != "OWNER":
        raise HTTPException(403, "Only an owner can transfer ownership")
    if membership.user_id == actor.id and payload.status == "SUSPENDED":
        raise HTTPException(400, "You cannot suspend your own active membership")
    if payload.role == "OWNER" and actor_membership.role != "OWNER":
        raise HTTPException(403, "Only an owner can grant owner role")

    active_owners = db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.organization_id == org.id,
            Membership.role == "OWNER",
            Membership.status == "ACTIVE",
        )
    ) or 0
    target_would_be_active_owner = payload.role == "OWNER" and payload.status == "ACTIVE"
    if active_owners <= 1 and membership.role == "OWNER" and not target_would_be_active_owner:
        raise HTTPException(400, "Organization must keep at least one active owner")

    membership.role = payload.role
    membership.status = payload.status
    membership.updated_at = utcnow()
    audit(
        db,
        org.id,
        actor.id,
        "member.updated",
        "membership",
        membership.id,
        {"role": membership.role, "status": membership.status},
    )
    db.commit()
    db.refresh(membership)
    return _member_out(db, membership)


@router.post("/invitations", response_model=InviteOut, status_code=201)
def invite(
    payload: InviteCreate,
    db: Session = Depends(get_db),
    context=Depends(actor_context),
):
    user, org, _ = require_admin(context)
    email = payload.email.strip().lower()
    # Prevent invitation spam/duplicate pending invites for the same organization/email.
    existing = db.scalar(
        select(Invitation).where(
            Invitation.organization_id == org.id,
            func.lower(Invitation.email) == email,
            Invitation.status == "PENDING",
            Invitation.expires_at > utcnow(),
        )
    )
    if existing:
        raise HTTPException(409, "A pending invitation already exists for this email")
    inv = Invitation(
        organization_id=org.id,
        email=email,
        role=payload.role,
        expires_at=utcnow() + timedelta(days=7),
    )
    db.add(inv)
    db.flush()
    audit(db, org.id, user.id, "member.invited", "invitation", inv.id, {"email": inv.email, "role": inv.role})
    db.commit()
    db.refresh(inv)
    base = get_settings().app_public_url.rstrip("/")
    return InviteOut(
        id=inv.id,
        email=inv.email,
        role=inv.role,
        status=inv.status,
        expires_at=inv.expires_at,
        invite_url=f"{base}/?invite={inv.token}",
    )


@router.get("/invitations", response_model=list[InviteOut])
def invitations(db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = require_admin(context)
    rows = db.scalars(
        select(Invitation)
        .where(Invitation.organization_id == org.id)
        .order_by(Invitation.created_at.desc())
        .limit(100)
    ).all()
    base = get_settings().app_public_url.rstrip("/")
    return [
        InviteOut(
            id=i.id,
            email=i.email,
            role=i.role,
            status=i.status,
            expires_at=i.expires_at,
            invite_url=f"{base}/?invite={i.token}",
        )
        for i in rows
    ]


@router.post("/invitations/{token}/accept")
def accept_invitation(token: str, db: Session = Depends(get_db), user: User = Depends(actor_user)):
    inv = db.scalar(select(Invitation).where(Invitation.token == token, Invitation.status == "PENDING").with_for_update())
    if not inv:
        raise HTTPException(404, "Invitation not found or already used")
    if inv.expires_at < utcnow():
        inv.status = "EXPIRED"
        db.commit()
        raise HTTPException(410, "Invitation expired")
    org = db.get(Organization, inv.organization_id)
    if not org or org.status != "ACTIVE":
        raise HTTPException(403, "Organization is not active")
    if user.email.lower() != inv.email.lower():
        raise HTTPException(403, "Invitation email does not match the current identity")
    existing = db.scalar(
        select(Membership)
        .where(Membership.organization_id == inv.organization_id, Membership.user_id == user.id)
        .with_for_update()
    )
    if existing:
        existing.role = inv.role
        existing.status = "ACTIVE"
        existing.updated_at = utcnow()
    else:
        db.add(Membership(organization_id=inv.organization_id, user_id=user.id, role=inv.role, status="ACTIVE"))
    inv.status = "ACCEPTED"
    inv.accepted_at = utcnow()
    audit(db, inv.organization_id, user.id, "member.invitation_accepted", "invitation", inv.id, {"email": user.email})
    db.commit()
    return {"accepted": True, "organization_id": inv.organization_id, "role": inv.role}


@router.get("/usage", response_model=UsageOut)
def usage(db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = context
    u = ensure_usage(db, org.id)
    projects = db.scalar(select(func.count()).select_from(Project).where(Project.organization_id == org.id)) or 0
    db.commit()
    limits = PLANS.get(org.plan_code, PLANS["FREE"])
    return UsageOut(
        plan_code=org.plan_code,
        limits=limits,
        verification_runs=u.verification_runs,
        ai_explanations=u.ai_explanations,
        projects=projects,
        period_start=u.period_start,
    )


@router.get("/audit")
def audit_logs(limit: int = 100, db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = require_admin(context)
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.organization_id == org.id)
        .order_by(AuditLog.created_at.desc())
        .limit(min(max(limit, 1), 200))
    ).all()
    return [
        {
            "id": r.id,
            "actor_user_id": r.actor_user_id,
            "event_type": r.event_type,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "details": r.details,
            "created_at": r.created_at,
        }
        for r in rows
    ]
