from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models import GitHubInstallation, Organization, Project, Verification, WebhookEvent
from app.schemas import *  # noqa: F403
from app.services.ai import ai_configured, explain_result, test_ai_connection
from app.services.billing import configured as stripe_configured
from app.services.comparator import compare_behavior
from app.services.github_app import create_check, get_app, get_installation, installation_token, update_check, upsert_pr_comment
from app.services.k8s import KubernetesRunner, parse_result_from_logs
from app.services.tenant import PLANS, actor_context, audit, check_entitlement, ensure_usage, require_admin, require_member

router = APIRouter()
settings = get_settings()


def utcnow():
    return datetime.now(timezone.utc)


def normalize_repository(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().rstrip("/")
    if not value:
        return None
    if not value.startswith("https://github.com/"):
        raise HTTPException(422, "Repository must be an HTTPS GitHub repository URL")
    tail = value.removeprefix("https://github.com/")
    if tail.count("/") != 1 or any(part in {"", ".", ".."} for part in tail.split("/")):
        raise HTTPException(422, "Repository must use https://github.com/OWNER/REPOSITORY")
    return value

def verification_key(
    organization_id: str,
    repo: str,
    pr_number: int,
    sha: str,
    package: str,
    old_version: str,
    new_version: str,
    manifest: str,
) -> str:
    canonical = "|".join(
        [organization_id, repo.lower(), str(pr_number), sha, package.lower(), old_version, new_version, manifest]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_run_record(
    db: Session,
    org: Organization,
    project: Project,
    package_name: str,
    ecosystem: str,
    old_version: str,
    new_version: str,
    smoke_import: str | None,
    source: str = "manual",
    manifest_path: str | None = None,
    actor_user_id: str | None = None,
    verification_key: str | None = None,
) -> Verification:
    if not project.active:
        raise HTTPException(400, "Project is inactive")
    check_entitlement(db, org, "verification_runs")
    run = Verification(
        organization_id=org.id,
        project_id=project.id,
        package_name=package_name.strip(),
        ecosystem=ecosystem,
        old_version=old_version.strip(),
        new_version=new_version.strip(),
        smoke_import=smoke_import or package_name,
        source=source,
        status="QUEUED",
        manifest_path=manifest_path,
        verification_key=verification_key,
    )
    db.add(run)
    db.flush()
    audit(db, org.id, actor_user_id, "verification.created", "verification", run.id, {"source": source, "package": package_name})
    db.commit()
    db.refresh(run)
    return run


@router.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version, "environment": settings.environment}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok", "version": settings.app_version}


@router.get("/metrics")
def metrics(db: Session = Depends(get_db), context=Depends(actor_context)):
    """Small Prometheus-compatible metric surface for operational dashboards."""
    _, org, _ = context
    base = Verification.organization_id == org.id
    total = db.scalar(select(func.count()).select_from(Verification).where(base)) or 0
    running = db.scalar(select(func.count()).select_from(Verification).where(base, Verification.status.in_(["QUEUED", "RUNNING", "RECONCILING"]))) or 0
    completed = db.scalar(select(func.count()).select_from(Verification).where(base, Verification.status == "COMPLETED")) or 0
    failed = db.scalar(select(func.count()).select_from(Verification).where(base, Verification.status == "FAILED")) or 0
    return {
        "organization_id": org.id,
        "verification_runs_total": total,
        "verification_runs_running": running,
        "verification_runs_completed": completed,
        "verification_runs_failed": failed,
        "app_version": settings.app_version,
    }


@router.get("/integrations", response_model=IntegrationOut)
def integrations():
    return IntegrationOut(
        kubernetes=settings.k8s_enabled,
        ai_enabled=settings.ai_enabled,
        ai_configured=ai_configured(),
        ai_model=settings.ai_model,
        github_configured=bool(settings.github_app_id and settings.normalized_private_key and settings.github_webhook_secret),
        github_app_url=settings.github_install_url,
        github_webhook_url=settings.github_webhook_url if settings.github_app_id else None,
        github_check_name="Dependency Change Verification",
        stripe_configured=stripe_configured(),
    )


@router.post("/github/test")
async def github_test(context=Depends(actor_context)):
    require_admin(context)
    if not settings.github_app_id or not settings.normalized_private_key:
        raise HTTPException(400, "GitHub App credentials are not configured")
    try:
        data = await get_app()
        return {"ok": True, "id": data.get("id"), "name": data.get("name"), "slug": data.get("slug"), "html_url": data.get("html_url")}
    except Exception as exc:
        raise HTTPException(502, f"GitHub App connection failed: {type(exc).__name__}: {exc}")


@router.post("/ai/test")
def ai_test(context=Depends(actor_context)):
    require_admin(context)
    if not settings.ai_enabled:
        raise HTTPException(400, "AI is disabled")
    if not ai_configured():
        raise HTTPException(400, "AI credentials are not configured")
    try:
        return {"ok": True, "model": settings.ai_model, "message": test_ai_connection()}
    except Exception as exc:
        raise HTTPException(502, f"AI provider connection failed: {type(exc).__name__}: {exc}")


@router.get("/github/status")
def github_status():
    configured = bool(settings.github_app_id and settings.normalized_private_key and settings.github_webhook_secret)
    return {
        "configured": configured,
        "app_id": settings.github_app_id,
        "app_slug": settings.github_app_slug,
        "installation_url": settings.github_install_url,
        "setup_url": settings.github_setup_url,
        "webhook_url": settings.github_webhook_url,
        "events": ["pull_request", "installation", "installation_repositories"],
        "supported_actions": ["opened", "reopened", "synchronize", "ready_for_review"],
        "check_name": "Dependency Change Verification",
    }


@router.get("/github/install-url")
def github_install_url(context=Depends(actor_context)):
    _, org, membership = require_admin(context)
    if not settings.github_install_url:
        raise HTTPException(400, "GitHub App slug is not configured")
    return {"url": f"{settings.github_install_url}?state={org.id}", "organization_id": org.id, "role": membership.role}


@router.get("/github/setup")
async def github_setup(installation_id: int, state: str):
    """GitHub App post-install setup hook.

    The installation id is verified against GitHub before it is linked locally. The
    state value identifies the DCV organization selected before the user left DCV.
    """
    if not state or not installation_id:
        raise HTTPException(400, "installation_id and state are required")
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.id == state, Organization.status == "ACTIVE"))
        if not org:
            raise HTTPException(404, "Organization not found")
        details = await get_installation(installation_id)
        inst = db.get(GitHubInstallation, installation_id)
        if not inst:
            inst = GitHubInstallation(installation_id=installation_id)
        account = details.get("account") or {}
        inst.account_login = account.get("login")
        inst.account_type = account.get("type")
        inst.deleted_at = None
        inst.suspended_at = None
        existing_org = inst.organization_id
        if existing_org and existing_org != org.id:
            raise HTTPException(409, "GitHub installation is already attached to another organization")
        inst.organization_id = org.id
        inst.updated_at = utcnow()
        db.add(inst)
        db.execute(
            text("UPDATE webhook_events SET organization_id=:o,status='QUEUED',next_attempt_at=NULL,updated_at=NOW() WHERE installation_id=:i AND status='WAITING_FOR_ORG'"),
            {"o": org.id, "i": installation_id},
        )
        audit(db, org.id, None, "github.installation_attached", "github_installation", str(installation_id), {"account": inst.account_login, "source": "setup_url"})
        db.commit()
        return RedirectResponse(url=f"{settings.app_public_url.rstrip('/')}/?github=connected&installation_id={installation_id}", status_code=303)
    finally:
        db.close()


@router.get("/github/webhook-events")
def github_webhook_events(limit: int = 50, db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = context
    limit = min(max(limit, 1), 100)
    rows = db.scalars(select(WebhookEvent).where(WebhookEvent.organization_id == org.id).order_by(WebhookEvent.created_at.desc()).limit(limit)).all()
    return [
        {
            "delivery_id": r.delivery_id,
            "event": r.event_name,
            "action": r.action,
            "repository": r.repository,
            "status": r.status,
            "attempts": r.attempts,
            "next_attempt_at": r.next_attempt_at,
            "last_error": r.last_error,
            "created_at": r.created_at,
            "processed_at": r.processed_at,
        }
        for r in rows
    ]


@router.get("/github/installations")
def github_installations(db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = context
    rows = db.scalars(
        select(GitHubInstallation).where(GitHubInstallation.organization_id == org.id).order_by(GitHubInstallation.created_at.desc())
    ).all()
    return [
        {
            "installation_id": r.installation_id,
            "organization_id": r.organization_id,
            "account_login": r.account_login,
            "account_type": r.account_type,
            "suspended_at": r.suspended_at,
            "deleted_at": r.deleted_at,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


@router.post("/github/installations/{installation_id}/attach")
def attach_installation(installation_id: int, db: Session = Depends(get_db), context=Depends(actor_context)):
    user, org, membership = require_admin(context)
    inst = db.get(GitHubInstallation, installation_id)
    if not inst:
        raise HTTPException(404, "GitHub installation not found")
    if inst.organization_id and inst.organization_id != org.id:
        raise HTTPException(409, "GitHub installation is already attached to another organization")
    inst.organization_id = org.id
    inst.updated_at = utcnow()
    db.execute(
        text("UPDATE webhook_events SET organization_id=:o,status='QUEUED',next_attempt_at=NULL,updated_at=NOW() WHERE installation_id=:i AND status='WAITING_FOR_ORG'"),
        {"o": org.id, "i": installation_id},
    )
    audit(db, org.id, user.id, "github.installation_attached", "github_installation", str(installation_id), {"account": inst.account_login})
    db.commit()
    return {"ok": True, "installation_id": installation_id, "organization_id": org.id}


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = context
    base = Verification.organization_id == org.id
    total = db.scalar(select(func.count()).select_from(Verification).where(base)) or 0
    rows = db.execute(select(Verification.decision, func.count()).where(base, Verification.decision.is_not(None)).group_by(Verification.decision)).all()
    mapping = {r[0]: r[1] for r in rows}
    running = db.scalar(select(func.count()).select_from(Verification).where(base, Verification.status.in_(["QUEUED", "RUNNING", "RECONCILING"]))) or 0
    return StatsOut(
        total=total,
        pass_count=mapping.get("PASS", 0),
        review_count=mapping.get("REVIEW", 0),
        block_count=mapping.get("BLOCK", 0),
        running_count=running,
    )


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = context
    return db.scalars(select(Project).where(Project.organization_id == org.id).order_by(Project.created_at.asc())).all()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), context=Depends(actor_context)):
    user, org, _ = require_admin(context)
    name = payload.name.strip()
    if db.scalar(select(Project).where(Project.organization_id == org.id, func.lower(Project.name) == name.lower())):
        raise HTTPException(409, "Project already exists")
    locked_org = db.scalar(select(Organization).where(Organization.id == org.id).with_for_update())
    limit = PLANS.get(locked_org.plan_code if locked_org else org.plan_code, PLANS["FREE"])["projects"]
    current = db.scalar(select(func.count()).select_from(Project).where(Project.organization_id == org.id)) or 0
    if limit >= 0 and current >= limit:
        raise HTTPException(402, "Project limit reached for your plan")
    repository = normalize_repository(payload.repository)
    project = Project(organization_id=org.id, name=name, repository=repository, default_ecosystem=payload.default_ecosystem)
    db.add(project)
    audit(db, org.id, user.id, "project.created", "project", project.id, {"name": name})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Project already exists")
    db.refresh(project)
    return project


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db), context=Depends(actor_context)):
    user, org, _ = require_admin(context)
    project = db.scalar(select(Project).where(Project.id == project_id, Project.organization_id == org.id))
    if not project:
        raise HTTPException(404, "Project not found")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = str(changes["name"]).strip()
        duplicate = db.scalar(
            select(Project).where(Project.organization_id == org.id, func.lower(Project.name) == changes["name"].lower(), Project.id != project.id)
        )
        if duplicate:
            raise HTTPException(409, "Project already exists")
    for key, value in changes.items():
        setattr(project, key, value)
    project.updated_at = utcnow()
    audit(db, org.id, user.id, "project.updated", "project", project.id, changes)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Project already exists")
    db.refresh(project)
    return project


@router.get("/verifications", response_model=list[VerificationOut])
def list_verifications(limit: int = 100, project_id: str | None = None, db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = context
    limit = min(max(limit, 1), 200)
    stmt = select(Verification).where(Verification.organization_id == org.id).order_by(Verification.created_at.desc()).limit(limit)
    if project_id:
        stmt = stmt.where(Verification.project_id == project_id)
    return db.scalars(stmt).all()


@router.get("/verifications/{run_id}", response_model=VerificationOut)
def get_verification(run_id: str, db: Session = Depends(get_db), context=Depends(actor_context)):
    _, org, _ = context
    run = db.scalar(select(Verification).where(Verification.id == run_id, Verification.organization_id == org.id))
    if not run:
        raise HTTPException(404, "Verification not found")
    return run


def apply_result(run: Verification, result: dict, ai: bool = True):
    comparison = result.get("comparison") or compare_behavior(result.get("old", {}), result.get("new", {}), run.project, run.package_name)
    result["comparison"] = comparison
    run.result_json = result
    run.decision = comparison["decision"]
    run.severity = comparison["severity"]
    run.summary = comparison["reason"]
    run.status = "COMPLETED"
    run.finished_at = utcnow()
    run.error_message = None
    run.ai_updated_at = utcnow()
    if settings.ai_auto_explain and ai_configured() and ai:
        run.ai_status = "QUEUED"
        run.ai_next_attempt_at = utcnow()
    else:
        run.ai_status = "DISABLED"
        run.ai_next_attempt_at = None


def _create_k8s_run(db: Session, run: Verification):
    if not settings.k8s_enabled:
        apply_result(
            run,
            {
                "old": {},
                "new": {},
                "comparison": {
                    "decision": "PASS",
                    "severity": "LOW",
                    "score": 0,
                    "reason": "Kubernetes is disabled; deterministic test mode.",
                    "deltas": {},
                },
            },
            ai=False,
        )
        db.commit()
        return run
    try:
        runner = KubernetesRunner()
        run.k8s_job_name = runner.create_job(run.id, run.ecosystem, run.package_name, run.old_version, run.new_version, run.smoke_import)
        run.status = "RUNNING"
        run.started_at = utcnow()
        db.commit()
    except Exception as exc:
        run.status = "FAILED"
        run.decision = "BLOCK"
        run.severity = "HIGH"
        run.error_message = f"{type(exc).__name__}: {exc}"
        run.summary = "The verification job could not be created."
        run.finished_at = utcnow()
        db.commit()
    return run


@router.post("/verifications", response_model=VerificationOut, status_code=202)
def create_verification(payload: VerificationCreate, db: Session = Depends(get_db), context=Depends(actor_context)):
    user, org, _ = require_member(context)
    if payload.project_id:
        project = db.scalar(select(Project).where(Project.id == payload.project_id, Project.organization_id == org.id))
    else:
        project = db.scalar(select(Project).where(Project.organization_id == org.id).order_by(Project.created_at.asc()).limit(1))
    if not project:
        raise HTTPException(400, "A project is required before running a verification")
    run = create_run_record(
        db,
        org,
        project,
        payload.package_name,
        payload.ecosystem,
        payload.old_version,
        payload.new_version,
        payload.smoke_import,
        actor_user_id=user.id,
    )
    return _create_k8s_run(db, run)


@router.post("/verifications/{run_id}/rerun", response_model=VerificationOut, status_code=202)
def rerun_verification(run_id: str, db: Session = Depends(get_db), context=Depends(actor_context)):
    user, org, _ = require_member(context)
    source = db.scalar(select(Verification).where(Verification.id == run_id, Verification.organization_id == org.id))
    if not source:
        raise HTTPException(404, "Verification not found")
    project = db.scalar(select(Project).where(Project.id == source.project_id, Project.organization_id == org.id))
    if not project:
        raise HTTPException(404, "Project not found")
    run = create_run_record(
        db,
        org,
        project,
        source.package_name,
        source.ecosystem,
        source.old_version,
        source.new_version,
        source.smoke_import,
        source="manual_rerun",
        actor_user_id=user.id,
    )
    return _create_k8s_run(db, run)


@router.post("/verifications/{run_id}/explain", response_model=ExplainOut)
def explain_verification(run_id: str, db: Session = Depends(get_db), context=Depends(actor_context)):
    user, org, _ = require_member(context)
    run = db.scalar(select(Verification).where(Verification.id == run_id, Verification.organization_id == org.id))
    if not run or not run.result_json:
        raise HTTPException(404, "Verification result not available")
    if not ai_configured():
        raise HTTPException(400, "AI is not configured")
    if run.ai_explanation:
        return ExplainOut(explanation=run.ai_explanation)
    run.ai_status = "RUNNING"
    run.ai_attempts += 1
    run.ai_next_attempt_at = None
    run.ai_updated_at = utcnow()
    db.commit()
    try:
        check_entitlement(db, org, "ai_explanations")
        explanation = explain_result(run.package_name, run.old_version, run.new_version, run.result_json, allow_fallback=False)
        run.ai_explanation = explanation
        run.ai_error = None
        run.ai_status = "COMPLETED"
        run.ai_updated_at = utcnow()
        audit(db, org.id, user.id, "verification.ai_explained", "verification", run.id, {"provider": "openai", "model": settings.ai_model})
        db.commit()
        return ExplainOut(explanation=explanation)
    except HTTPException as exc:
        db.rollback()
        current = db.get(Verification, run_id)
        if current:
            current.ai_status = "FAILED"
            current.ai_error = str(exc.detail)
            current.ai_updated_at = utcnow()
            db.commit()
        raise
    except Exception as exc:
        db.rollback()
        current = db.get(Verification, run_id)
        if current:
            current.ai_status = "FAILED"
            current.ai_error = f"{type(exc).__name__}: {exc}"
            current.ai_updated_at = utcnow()
            db.commit()
        raise HTTPException(502, "AI explanation provider failed")


def github_conclusion(decision):
    return {"PASS": "success", "REVIEW": "action_required", "BLOCK": "failure"}.get(decision or "BLOCK", "failure")


def github_check_summary(run: Verification):
    evidence = run.result_json or {}
    comp = evidence.get("comparison") or {}
    d = comp.get("deltas") or {}
    title = f"{run.decision or 'RUNNING'} — {run.package_name} {run.old_version} → {run.new_version}"
    summary = run.summary or "Verification is running."
    txt = (
        f"Decision: {run.decision or 'RUNNING'} ({run.severity or 'PENDING'})\n\n"
        f"Behavior score: {comp.get('score', '—')}\n"
        f"New network endpoints: {d.get('network_count_delta', 0)}\n"
        f"New process behaviors: {d.get('process_count_delta', 0)}\n"
        f"File delta: {d.get('file_count_delta', 0)}\n"
        f"Transitive dependency changes: {d.get('dependency_version_change_count', 0)}\n"
        f"Smoke runtime regression: {d.get('smoke_regression_percent', '—')}%\n\n"
        f"Manifest: {run.manifest_path or 'manual'}\n"
        f"AI status: {run.ai_status}\n"
        f"Verification model: {evidence.get('verification_model', 'install + runtime verification')}"
    )
    if run.ai_explanation:
        txt += "\n\nAI explanation:\n" + run.ai_explanation[:6000]
    return title, summary, txt


async def sync_github_result(run: Verification, force: bool = False):
    """Publish or refresh a completed GitHub Check.

    The reconciliation loop owns the creation/publish claim for normal completion;
    the force path is used only to refresh an existing check after an AI explanation.
    """
    if run.github_published_at and not force:
        return
    if not run.github_repo or not run.github_installation_id or not run.github_sha:
        return
    db = SessionLocal()
    try:
        current = db.get(Verification, run.id)
        if not current:
            return
        token = await installation_token(int(current.github_installation_id), current.github_repo)
        if not current.github_check_run_id:
            current.github_check_run_id = await create_check(
                token,
                current.github_repo,
                str(current.github_sha),
                f"Dependency Change Verification / {current.package_name}",
                current.summary or "Verification completed.",
                f"{settings.app_public_url.rstrip('/')}/?run={current.id}",
            )
            db.commit()
        title, summary, txt = github_check_summary(current)
        await update_check(
            token,
            current.github_repo,
            int(current.github_check_run_id),
            github_conclusion(current.decision),
            title,
            summary,
            txt,
            f"{settings.app_public_url.rstrip('/')}/?run={current.id}",
        )
        if settings.github_pr_comments and current.github_pr:
            marker = f"<!-- dcv-run:{current.id} -->"
            comment = (
                f"{marker}\n## Dependency Change Verification\n\n**{title}**\n\n{summary}\n\n"
                f"```text\n{txt[:9000]}\n```\n\n[Open DCV run]({settings.app_public_url.rstrip('/')}/?run={current.id})"
            )
            current.github_comment_id = await upsert_pr_comment(token, current.github_repo, int(current.github_pr), marker, comment)
        current.github_published_at = utcnow()
        current.github_publish_claimed_at = None
        current.error_message = None
        current.updated_at = utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        current = db.get(Verification, run.id)
        if current:
            current.error_message = f"GitHub publication failed: {type(exc).__name__}: {exc}"
            current.updated_at = utcnow()
            db.commit()
    finally:
        db.close()


async def reconcile_run(run_id: str):
    db = SessionLocal()
    try:
        run = db.get(Verification, run_id)
        if not run or run.status != "RECONCILING":
            return
        runner = KubernetesRunner()
        state, logs = runner.job_state(run.k8s_job_name or "")
        if state == "UNKNOWN":
            run.status = "FAILED"
            run.decision = "BLOCK"
            run.severity = "HIGH"
            run.summary = "The verification job is no longer available."
            run.error_message = "Kubernetes Job not found or not readable."
            run.finished_at = utcnow()
        elif state == "ERROR":
            run.status = "RUNNING"
            run.error_message = "Temporary Kubernetes API error; verification will be retried."
        elif state in {"SUCCEEDED", "FAILED"}:
            result = parse_result_from_logs(logs or "")
            if result:
                apply_result(run, result)
            else:
                run.status = "FAILED"
                run.decision = "BLOCK"
                run.severity = "HIGH"
                run.summary = "The verification job finished without a valid result record."
                run.error_message = "No VERIFICATION_RESULT record was found."
                run.finished_at = utcnow()
        else:
            run.status = "RUNNING"
        run.updated_at = utcnow()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


async def ai_worker_loop():
    if not settings.ai_auto_explain:
        return
    while True:
        selected_id = None
        try:
            db = SessionLocal()
            try:
                now = utcnow()
                db.execute(
                    text("""UPDATE verifications SET ai_status='QUEUED',ai_updated_at=NOW(),ai_error='Recovered stale AI worker state.'
                           WHERE ai_status='RUNNING' AND ai_updated_at < NOW()-INTERVAL '10 minutes' AND ai_attempts < :m"""),
                    {"m": settings.ai_max_attempts},
                )
                db.commit()
                run = db.scalars(
                    select(Verification)
                    .where(
                        Verification.status == "COMPLETED",
                        Verification.ai_status == "QUEUED",
                        Verification.ai_attempts < settings.ai_max_attempts,
                        (Verification.ai_next_attempt_at.is_(None)) | (Verification.ai_next_attempt_at <= now),
                    )
                    .order_by(Verification.updated_at.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                ).first()
                if not run or not ai_configured():
                    if run and not ai_configured():
                        run.ai_status = "DISABLED"
                        run.ai_next_attempt_at = None
                        run.ai_updated_at = now
                        db.commit()
                    selected_id = None
                else:
                    selected_id = run.id
                    run.ai_status = "RUNNING"
                    run.ai_attempts += 1
                    run.ai_next_attempt_at = None
                    run.ai_updated_at = now
                    package_name = run.package_name
                    old_version = run.old_version
                    new_version = run.new_version
                    evidence = run.result_json or {}
                    org_id = run.organization_id
                    db.commit()
            finally:
                db.close()

            if selected_id is not None:
                try:
                    db2 = SessionLocal()
                    try:
                        org = db2.get(Organization, org_id)
                        if not org:
                            raise HTTPException(404, "Organization not found")
                        check_entitlement(db2, org, "ai_explanations")
                        explanation = explain_result(package_name, old_version, new_version, evidence, allow_fallback=False)
                        current = db2.get(Verification, selected_id)
                        if not current:
                            raise HTTPException(404, "Verification no longer exists")
                        current.ai_explanation = explanation
                        current.ai_error = None
                        current.ai_status = "COMPLETED"
                        current.ai_next_attempt_at = None
                        current.ai_updated_at = utcnow()
                        db2.commit()
                    except Exception:
                        db2.rollback()
                        raise
                    finally:
                        db2.close()
                    await sync_github_result_by_id(selected_id, force=True)
                except HTTPException as exc:
                    db3 = SessionLocal()
                    try:
                        current = db3.get(Verification, selected_id)
                        if current:
                            current.ai_status = "FAILED"
                            current.ai_error = str(exc.detail)
                            current.ai_next_attempt_at = None
                            current.ai_updated_at = utcnow()
                            db3.commit()
                    finally:
                        db3.close()
                except Exception as exc:
                    db3 = SessionLocal()
                    try:
                        current = db3.get(Verification, selected_id)
                        if current:
                            should_retry = current.ai_attempts < settings.ai_max_attempts
                            current.ai_status = "QUEUED" if should_retry else "FAILED"
                            current.ai_error = f"{type(exc).__name__}: {exc}"
                            current.ai_next_attempt_at = utcnow() + timedelta(seconds=min(300, 2 ** current.ai_attempts)) if should_retry else None
                            current.ai_updated_at = utcnow()
                            db3.commit()
                    finally:
                        db3.close()
        except Exception:
            # A transient worker/database/provider issue must never terminate the worker loop.
            pass
        await asyncio.sleep(2)


async def reconciliation_loop():
    if not settings.k8s_enabled:
        return
    while True:
        db = SessionLocal()
        ids: list[str] = []
        publish_ids: list[str] = []
        try:
            now = utcnow()
            stale_reconcile = now - timedelta(minutes=settings.reconcile_stale_minutes)
            db.execute(
                text("UPDATE verifications SET status='RUNNING',updated_at=NOW() WHERE status='RECONCILING' AND updated_at<:c"),
                {"c": stale_reconcile},
            )
            db.execute(
                text("UPDATE verifications SET github_publish_claimed_at=NULL WHERE github_published_at IS NULL AND github_publish_claimed_at<:c"),
                {"c": now - timedelta(minutes=settings.github_publish_stale_minutes)},
            )
            db.commit()

            runs = db.scalars(
                select(Verification)
                .where(Verification.status == "RUNNING")
                .order_by(Verification.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(25)
            ).all()
            for run in runs:
                run.status = "RECONCILING"
                run.updated_at = now
                ids.append(run.id)
            db.commit()

            pending = db.scalars(
                select(Verification)
                .where(
                    Verification.status.in_(["COMPLETED", "FAILED"]),
                    Verification.github_repo.is_not(None),
                    Verification.github_installation_id.is_not(None),
                    Verification.github_sha.is_not(None),
                    Verification.github_published_at.is_(None),
                    ((Verification.github_publish_claimed_at.is_(None)) | (Verification.github_publish_claimed_at <= now - timedelta(minutes=settings.github_publish_stale_minutes))),
                )
                .order_by(Verification.updated_at.asc())
                .with_for_update(skip_locked=True)
                .limit(10)
            ).all()
            for run in pending:
                run.github_publish_claimed_at = now
                publish_ids.append(run.id)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

        for run_id in ids:
            await reconcile_run(run_id)
        for run_id in publish_ids:
            await sync_github_result_by_id(run_id)
        await asyncio.sleep(3)


async def sync_github_result_by_id(run_id: str, force: bool = False):
    db = SessionLocal()
    try:
        run = db.get(Verification, run_id)
        if not run:
            return
        run_id_value = run.id
    finally:
        db.close()
    detached = Verification(id=run_id_value)
    await sync_github_result(detached, force=force)
