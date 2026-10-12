from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.models import GitHubInstallation, Organization, Project, Verification, WebhookEvent
from app.services.dependency_parser import changed_dependencies, is_supported_dependency_manifest
from app.services.github_app import (
    create_check,
    find_check,
    get_content,
    github_configured,
    installation_token,
    list_pr_files,
    update_check,
    upsert_pr_comment,
    verify_signature,
)
from app.services.k8s import KubernetesRunner
from app.services.tenant import audit, check_entitlement

router = APIRouter()
settings = get_settings()
SUPPORTED_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}


def repo_url(repo: str) -> str:
    return f"https://github.com/{repo}".rstrip("/")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_key(organization_id: str, repo: str, pr_number: int, sha: str, package: str, old: str, new: str, manifest: str) -> str:
    from app.api.routes import verification_key
    return verification_key(organization_id, repo, pr_number, sha, package, old, new, manifest)


@router.post("/github", status_code=202)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
):
    body = await request.body()
    if not github_configured() or not verify_signature(body, x_hub_signature_256):
        raise HTTPException(401, "Invalid GitHub webhook signature")
    if not x_github_delivery:
        raise HTTPException(400, "Missing X-GitHub-Delivery header")
    payload = await request.json()
    action = payload.get("action")
    installation_id = (payload.get("installation") or {}).get("id")
    repo = (payload.get("repository") or {}).get("full_name")
    db = SessionLocal()
    try:
        existing = db.scalar(select(WebhookEvent).where(WebhookEvent.delivery_id == x_github_delivery))
        if existing:
            return {"accepted": True, "duplicate": True, "delivery_id": x_github_delivery}
        org_id = None
        if installation_id:
            inst = db.get(GitHubInstallation, int(installation_id))
            org_id = inst.organization_id if inst else None
        if not org_id and repo:
            project = db.scalar(select(Project).where(Project.repository == repo_url(repo)))
            org_id = project.organization_id if project else None
        status = "QUEUED"
        if x_github_event == "pull_request" and action not in SUPPORTED_ACTIONS:
            status = "IGNORED"
        if x_github_event not in {"pull_request", "installation", "installation_repositories"}:
            status = "IGNORED"
        event = WebhookEvent(
            organization_id=org_id,
            delivery_id=x_github_delivery,
            event_name=x_github_event or "unknown",
            action=action,
            repository=repo,
            installation_id=int(installation_id) if installation_id else None,
            payload=payload,
            status=status,
        )
        db.add(event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return {"accepted": True, "duplicate": True, "delivery_id": x_github_delivery}
        return {"accepted": True, "queued": status == "QUEUED", "delivery_id": x_github_delivery}
    finally:
        db.close()


async def process_webhook_event(event_id: str):
    db = SessionLocal()
    try:
        event = db.get(WebhookEvent, event_id)
        if not event or event.status != "PROCESSING":
            return
        p = event.payload
        if event.event_name == "installation":
            inst_payload = p.get("installation") or {}
            iid = int(inst_payload.get("id"))
            account = inst_payload.get("account") or {}
            existing = db.get(GitHubInstallation, iid)
            if not existing:
                existing = GitHubInstallation(installation_id=iid)
            existing.account_login = account.get("login")
            existing.account_type = account.get("type")
            existing.updated_at = utcnow()
            if event.action == "created":
                existing.deleted_at = None
                existing.suspended_at = None
            elif event.action == "deleted":
                existing.deleted_at = utcnow()
            elif event.action == "suspend":
                existing.suspended_at = utcnow()
            elif event.action == "unsuspend":
                existing.suspended_at = None
            db.add(existing)
            event.status = "COMPLETED"
            event.processed_at = utcnow()
            event.updated_at = utcnow()
            db.commit()
            return

        if event.event_name == "installation_repositories":
            event.status = "COMPLETED"
            event.processed_at = utcnow()
            event.updated_at = utcnow()
            db.commit()
            return

        if event.event_name != "pull_request" or event.action not in SUPPORTED_ACTIONS:
            event.status = "IGNORED"
            event.processed_at = utcnow()
            event.updated_at = utcnow()
            db.commit()
            return

        installation_id = int(event.installation_id or 0)
        repo = event.repository or ""
        pr = p.get("pull_request") or {}
        pr_number = int(pr.get("number"))
        head_sha = (pr.get("head") or {}).get("sha")
        base_sha = (pr.get("base") or {}).get("sha")
        head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name") or repo
        if not installation_id or not repo or not head_sha or not base_sha:
            raise RuntimeError("GitHub PR payload missing installation, repository or SHA")

        org_id = event.organization_id
        if not org_id:
            project_match = db.scalar(select(Project).where(Project.repository == repo_url(repo)))
            org_id = project_match.organization_id if project_match else None
        if not org_id:
            event.status = "WAITING_FOR_ORG"
            event.last_error = "GitHub installation is not linked to a DCV organization. Install/finish GitHub App setup from the DCV organization."
            event.updated_at = utcnow()
            db.commit()
            return

        org = db.get(Organization, org_id)
        if not org or org.status != "ACTIVE":
            raise RuntimeError("Target DCV organization is not active")

        project = db.scalar(select(Project).where(Project.organization_id == org_id, Project.repository == repo_url(repo)))
        if not project:
            project = Project(
                organization_id=org_id,
                name=repo.split("/")[-1][:120],
                repository=repo_url(repo),
                default_ecosystem="python",
                github_installation_id=installation_id,
            )
            db.add(project)
            try:
                db.commit()
                db.refresh(project)
            except IntegrityError:
                db.rollback()
                project = db.scalar(select(Project).where(Project.organization_id == org_id, Project.repository == repo_url(repo)))
        project.github_installation_id = installation_id
        project.updated_at = utcnow()
        db.commit()

        if not settings.github_auto_verify or not project.auto_verify_pull_requests or not project.active:
            event.status = "IGNORED"
            event.last_error = "Automatic pull-request verification is disabled for this project."
            event.processed_at = utcnow()
            event.updated_at = utcnow()
            db.commit()
            return

        token = await installation_token(installation_id, repo)
        files = await list_pr_files(token, repo, pr_number)
        if len(files) >= 1000:
            raise RuntimeError("Pull request changes reach GitHub's 1000-file pagination limit; verification was not started")

        changes = []
        for item in files:
            path = item.get("filename") or ""
            ecosystem = is_supported_dependency_manifest(path)
            if not ecosystem:
                continue
            status = item.get("status")
            try:
                old_text = await get_content(token, repo, path, base_sha)
            except Exception:
                if status == "added":
                    old_text = ""
                else:
                    raise RuntimeError(f"Unable to read base manifest {path}")
            if status == "removed":
                continue
            new_text = await get_content(token, head_repo, path, head_sha)
            changes.extend(changed_dependencies(ecosystem, old_text, new_text, path))

        # A repo may change package.json and package-lock.json for the same version;
        # verify the package once and prefer the package manifest as the user-facing source.
        deduped = {}
        for change in changes:
            key = (change.package.lower(), change.old_version, change.new_version, change.ecosystem)
            existing = deduped.get(key)
            if existing is None or (existing.manifest.endswith("package-lock.json") and change.manifest.endswith("package.json")):
                deduped[key] = change
        changes = list(deduped.values())

        if not changes:
            check_name = "Dependency Change Verification"
            check_id = await find_check(token, repo, head_sha, check_name)
            if check_id is None:
                check_id = await create_check(
                    token,
                    repo,
                    head_sha,
                    check_name,
                    "No supported dependency manifest change detected.",
                    f"{settings.app_public_url.rstrip('/')}/?repo={repo}",
                )
            await update_check(
                token,
                repo,
                check_id,
                "success",
                "No dependency changes",
                "No supported dependency manifest change was detected.",
                "Supported manifests: requirements*.txt, pyproject.toml, poetry.lock, Pipfile.lock, package.json, package-lock.json.",
                f"{settings.app_public_url.rstrip('/')}/?repo={repo}",
            )
            event.status = "COMPLETED"
            event.processed_at = utcnow()
            event.last_error = None
            event.updated_at = utcnow()
            db.commit()
            return

        from app.api.routes import github_check_summary

        k8s = KubernetesRunner() if settings.k8s_enabled else None
        for change in changes:
            key = run_key(org_id, repo, pr_number, head_sha, change.package, change.old_version, change.new_version, change.manifest)
            existing = db.scalar(select(Verification).where(Verification.verification_key == key))
            if existing:
                continue

            check_entitlement(db, org, "verification_runs")
            run = Verification(
                organization_id=org_id,
                project_id=project.id,
                package_name=change.package,
                ecosystem=change.ecosystem,
                old_version=change.old_version,
                new_version=change.new_version,
                smoke_import=change.package,
                source="github_pr",
                manifest_path=change.manifest,
                github_repo=repo,
                github_pr=pr_number,
                github_sha=head_sha,
                github_installation_id=installation_id,
                verification_key=key,
                status="QUEUED",
            )
            db.add(run)
            audit(db, org.id, None, "verification.created", "verification", run.id, {"source": "github_pr", "package": change.package, "manifest": change.manifest})
            db.commit()
            db.refresh(run)

            try:
                run.github_check_run_id = await create_check(
                    token,
                    repo,
                    head_sha,
                    f"Dependency Change Verification / {change.package}",
                    f"Verifying {change.package} {change.old_version} → {change.new_version}",
                    f"{settings.app_public_url.rstrip('/')}/?run={run.id}",
                )
            except Exception as exc:
                run.error_message = f"GitHub Check creation failed: {type(exc).__name__}: {exc}"

            try:
                if k8s:
                    run.k8s_job_name = k8s.create_job(run.id, change.ecosystem, change.package, change.old_version, change.new_version, change.package)
                    run.status = "RUNNING"
                    run.started_at = utcnow()
                else:
                    run.status = "FAILED"
                    run.decision = "BLOCK"
                    run.severity = "HIGH"
                    run.summary = "Kubernetes verification is disabled."
                    run.finished_at = utcnow()
            except Exception as exc:
                run.status = "FAILED"
                run.decision = "BLOCK"
                run.severity = "HIGH"
                run.summary = "The verification job could not be created."
                run.error_message = f"{type(exc).__name__}: {exc}"
                run.finished_at = utcnow()
            db.commit()

            if run.status == "FAILED" and run.github_check_run_id:
                title, summary, txt = github_check_summary(run)
                await update_check(
                    token,
                    repo,
                    int(run.github_check_run_id),
                    "failure",
                    title,
                    summary,
                    txt,
                    f"{settings.app_public_url.rstrip('/')}/?run={run.id}",
                )
                if settings.github_pr_comments:
                    marker = f"<!-- dcv-run:{run.id} -->"
                    comment = f"{marker}\n## Dependency Change Verification\n\n**{title}**\n\n{summary}\n\n[Open DCV run]({settings.app_public_url.rstrip('/')}/?run={run.id})"
                    run.github_comment_id = await upsert_pr_comment(token, repo, pr_number, marker, comment)
                run.github_published_at = utcnow()
                db.commit()

        event.status = "COMPLETED"
        event.processed_at = utcnow()
        event.last_error = None
        event.updated_at = utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        event = db.get(WebhookEvent, event_id)
        if event:
            event.last_error = f"{type(exc).__name__}: {exc}"
            if event.attempts >= settings.webhook_max_attempts:
                event.status = "FAILED"
                event.processed_at = utcnow()
                event.next_attempt_at = None
            else:
                event.status = "QUEUED"
                event.next_attempt_at = utcnow() + timedelta(seconds=min(300, 2 ** max(event.attempts - 1, 0)))
            event.updated_at = utcnow()
            db.commit()
    finally:
        db.close()


async def webhook_worker_loop():
    while True:
        db = SessionLocal()
        ids: list[str] = []
        try:
            now = utcnow()
            cutoff = now - timedelta(minutes=settings.webhook_stale_minutes)
            db.execute(
                text("UPDATE webhook_events SET status='QUEUED',next_attempt_at=NULL,updated_at=NOW() WHERE status='PROCESSING' AND updated_at<:c AND attempts<:m"),
                {"c": cutoff, "m": settings.webhook_max_attempts},
            )
            db.execute(
                text("UPDATE webhook_events SET status='FAILED',processed_at=NOW(),updated_at=NOW(),last_error=COALESCE(last_error,'Maximum attempts exceeded.') WHERE status IN ('QUEUED','PROCESSING') AND attempts>=:m AND (next_attempt_at IS NULL OR next_attempt_at<=NOW())"),
                {"m": settings.webhook_max_attempts},
            )
            db.commit()
            events = db.scalars(
                select(WebhookEvent)
                .where(WebhookEvent.status == "QUEUED")
                .where((WebhookEvent.next_attempt_at.is_(None)) | (WebhookEvent.next_attempt_at <= now))
                .where(WebhookEvent.attempts < settings.webhook_max_attempts)
                .order_by(WebhookEvent.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(10)
            ).all()
            for event in events:
                event.status = "PROCESSING"
                event.attempts += 1
                event.updated_at = now
                event.next_attempt_at = None
                ids.append(event.id)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        for event_id in ids:
            await process_webhook_event(event_id)
        await asyncio.sleep(settings.webhook_poll_seconds)
