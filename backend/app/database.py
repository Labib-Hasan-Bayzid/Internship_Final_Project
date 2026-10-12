from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    """Bootstrap the schema and apply additive migrations for existing installs.

    This remains intentionally migration-lite for the packaged product. The critical
    invariant is that schema upgrades and tenant data repair always execute in every
    environment, while local demo identity creation is strictly dev-only.
    """
    from app import models  # noqa: F401
    from uuid import uuid4

    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(918273645)"))
        Base.metadata.create_all(bind=conn)
        migrations = {
            "projects": [
                ("organization_id", "VARCHAR(36)"), ("repository", "VARCHAR(255)"), ("default_ecosystem", "VARCHAR(20)"),
                ("active", "BOOLEAN"), ("auto_verify_pull_requests", "BOOLEAN"), ("github_installation_id", "INTEGER"),
                ("review_network_additions", "BOOLEAN"), ("review_process_additions", "BOOLEAN"), ("max_file_delta", "INTEGER"),
                ("block_on_test_failure", "BOOLEAN"), ("runtime_regression_review_percent", "INTEGER"),
                ("runtime_regression_block_percent", "INTEGER"), ("runtime_regression_min_ms", "INTEGER"),
                ("created_at", "TIMESTAMPTZ"), ("updated_at", "TIMESTAMPTZ"),
            ],
            "verifications": [
                ("organization_id", "VARCHAR(36)"), ("project_id", "VARCHAR(36)"), ("smoke_import", "VARCHAR(200)"),
                ("ai_status", "VARCHAR(20)"), ("ai_attempts", "INTEGER"), ("ai_error", "TEXT"), ("ai_next_attempt_at", "TIMESTAMPTZ"),
                ("ai_updated_at", "TIMESTAMPTZ"), ("source", "VARCHAR(30)"), ("github_published_at", "TIMESTAMPTZ"),
                ("github_comment_id", "INTEGER"), ("verification_key", "VARCHAR(128)"), ("github_publish_claimed_at", "TIMESTAMPTZ"),
                ("manifest_path", "VARCHAR(500)"), ("error_message", "TEXT"), ("updated_at", "TIMESTAMPTZ"), ("created_at", "TIMESTAMPTZ"),
            ],
            "webhook_events": [("organization_id", "VARCHAR(36)")],
            "billing_events": [("attempts", "INTEGER"), ("next_attempt_at", "TIMESTAMPTZ"), ("updated_at", "TIMESTAMPTZ"), ("error", "TEXT")],
            "subscriptions": [("last_stripe_event_created_at", "TIMESTAMPTZ")],
        }
        for table, cols in migrations.items():
            existing = {c["name"] for c in inspect(conn).get_columns(table)}
            for name, definition in cols:
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))

        # Safe defaults/backfills apply to production and local upgrades alike.
        conn.execute(text("UPDATE projects SET default_ecosystem='python' WHERE default_ecosystem IS NULL"))
        conn.execute(text("UPDATE projects SET active=TRUE WHERE active IS NULL"))
        conn.execute(text("UPDATE projects SET auto_verify_pull_requests=TRUE WHERE auto_verify_pull_requests IS NULL"))
        conn.execute(text("UPDATE projects SET review_network_additions=TRUE WHERE review_network_additions IS NULL"))
        conn.execute(text("UPDATE projects SET review_process_additions=TRUE WHERE review_process_additions IS NULL"))
        conn.execute(text("UPDATE projects SET max_file_delta=20 WHERE max_file_delta IS NULL"))
        conn.execute(text("UPDATE projects SET block_on_test_failure=TRUE WHERE block_on_test_failure IS NULL"))
        conn.execute(text("UPDATE projects SET runtime_regression_review_percent=50 WHERE runtime_regression_review_percent IS NULL"))
        conn.execute(text("UPDATE projects SET runtime_regression_block_percent=150 WHERE runtime_regression_block_percent IS NULL"))
        conn.execute(text("UPDATE projects SET runtime_regression_min_ms=100 WHERE runtime_regression_min_ms IS NULL"))
        conn.execute(text("UPDATE projects SET created_at=COALESCE(created_at,NOW()),updated_at=COALESCE(updated_at,created_at,NOW())"))
        conn.execute(text("UPDATE verifications SET ai_status='DISABLED' WHERE ai_status IS NULL"))
        conn.execute(text("UPDATE verifications SET ai_attempts=0 WHERE ai_attempts IS NULL"))
        conn.execute(text("UPDATE verifications SET ai_updated_at=COALESCE(ai_updated_at,updated_at,NOW()) WHERE ai_updated_at IS NULL"))
        conn.execute(text("UPDATE verifications SET source='manual' WHERE source IS NULL"))
        conn.execute(text("UPDATE verifications SET created_at=COALESCE(created_at,NOW()),updated_at=COALESCE(updated_at,created_at,NOW())"))
        conn.execute(text("UPDATE billing_events SET attempts=0 WHERE attempts IS NULL"))
        conn.execute(text("UPDATE billing_events SET updated_at=COALESCE(updated_at,created_at,NOW()) WHERE updated_at IS NULL"))

        # Backfill tenant from project when possible.
        conn.execute(text("""UPDATE verifications v SET organization_id=p.organization_id
                           FROM projects p WHERE v.project_id=p.id AND v.organization_id IS NULL"""))

        # Tenant-scoped project naming and verification idempotency.
        conn.execute(text("ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_name_key"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_project_org_name_idx ON projects(organization_id,name)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_project_org_repository_idx ON projects(organization_id,repository) WHERE repository IS NOT NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_verifications_verification_key_idx ON verifications(verification_key) WHERE verification_key IS NOT NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_verifications_github_pending ON verifications(status,github_repo,github_sha,github_published_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_webhook_events_queue ON webhook_events(status,next_attempt_at,created_at)"))

        if not settings.dev_identity_bootstrap:
            return

        # Local-only deterministic tenant bootstrap, including legacy data recovery.
        org_id = conn.execute(text("SELECT id FROM organizations WHERE slug=:slug AND status='ACTIVE' LIMIT 1"), {"slug": settings.default_org_slug}).scalar()
        data_orgs = conn.execute(text("""
            SELECT o.id
            FROM organizations o
            WHERE o.status='ACTIVE'
              AND (EXISTS (SELECT 1 FROM projects p WHERE p.organization_id=o.id)
                   OR EXISTS (SELECT 1 FROM verifications v WHERE v.organization_id=o.id))
            ORDER BY o.created_at ASC
        """)).fetchall()
        data_ids = [row[0] for row in data_orgs]
        if org_id and not conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM projects WHERE organization_id=:o) OR EXISTS (SELECT 1 FROM verifications WHERE organization_id=:o)"),
            {"o": org_id},
        ).scalar() and len(data_ids) == 1 and data_ids[0] != org_id:
            legacy_id = data_ids[0]
            temp_slug = settings.default_org_slug + "-legacy-" + str(uuid4())[:8]
            conn.execute(text("UPDATE organizations SET slug=:s,status='INACTIVE',updated_at=NOW() WHERE id=:o"), {"s": temp_slug, "o": org_id})
            org_id = legacy_id
            conn.execute(text("UPDATE organizations SET slug=:s,name=:n,status='ACTIVE',updated_at=NOW() WHERE id=:o"), {"s": settings.default_org_slug, "n": settings.default_org_name, "o": org_id})
        if not org_id:
            org_id = str(uuid4())
            conn.execute(text("""INSERT INTO organizations(id,name,slug,status,plan_code,created_at,updated_at)
                VALUES(:id,:name,:slug,'ACTIVE','FREE',NOW(),NOW())"""), {"id": org_id, "name": settings.default_org_name, "slug": settings.default_org_slug})

        user_id = conn.execute(text("SELECT id FROM users WHERE lower(email)=lower(:email) LIMIT 1"), {"email": settings.dev_identity_email}).scalar()
        if not user_id:
            user_id = str(uuid4())
            conn.execute(text("INSERT INTO users(id,email,name,is_active,created_at,updated_at) VALUES(:id,:email,:name,TRUE,NOW(),NOW())"), {"id": user_id, "email": settings.dev_identity_email, "name": settings.dev_identity_name})
        membership = conn.execute(text("SELECT id FROM memberships WHERE organization_id=:o AND user_id=:u LIMIT 1"), {"o": org_id, "u": user_id}).scalar()
        if not membership:
            conn.execute(text("INSERT INTO memberships(id,organization_id,user_id,role,status,created_at,updated_at) VALUES(:id,:o,:u,'OWNER','ACTIVE',NOW(),NOW())"), {"id": str(uuid4()), "o": org_id, "u": user_id})

        conn.execute(text("UPDATE projects SET organization_id=:o WHERE organization_id IS NULL"), {"o": org_id})
        conn.execute(text("UPDATE verifications v SET organization_id=:o WHERE v.organization_id IS NULL"), {"o": org_id})
        conn.execute(text("UPDATE webhook_events SET organization_id=:o WHERE organization_id IS NULL"), {"o": org_id})

        existing_project = conn.execute(text("SELECT id FROM projects WHERE organization_id=:o ORDER BY created_at LIMIT 1"), {"o": org_id}).scalar()
        if not existing_project:
            conn.execute(text("""INSERT INTO projects(id,organization_id,name,repository,default_ecosystem,active,auto_verify_pull_requests,
                review_network_additions,review_process_additions,max_file_delta,block_on_test_failure,
                runtime_regression_review_percent,runtime_regression_block_percent,runtime_regression_min_ms,created_at,updated_at)
                VALUES(:id,:o,'Default Application','https://github.com/example/example','python',TRUE,TRUE,TRUE,TRUE,20,TRUE,50,150,100,NOW(),NOW())"""), {"id": str(uuid4()), "o": org_id})
