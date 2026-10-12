from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ai_worker_loop, reconciliation_loop, router as api_router
from app.api.webhooks import router as webhook_router, webhook_worker_loop
from app.api.admin import router as admin_router
from app.api.billing import router as billing_router
from app.config import get_settings
from app.database import ensure_schema
from app.services.billing import billing_worker_loop


logger = logging.getLogger(__name__)
WORKER_SHUTDOWN_TIMEOUT_SECONDS = 10


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_schema()
    reconcile_task = asyncio.create_task(reconciliation_loop(), name="dcv-reconciliation-worker")
    webhook_task = asyncio.create_task(webhook_worker_loop(), name="dcv-webhook-worker")
    ai_task = asyncio.create_task(ai_worker_loop(), name="dcv-ai-worker")
    billing_task = asyncio.create_task(billing_worker_loop(), name="dcv-billing-worker")
    try:
        yield
    finally:
        tasks = (reconcile_task, webhook_task, ai_task, billing_task)
        for task in tasks:
            task.cancel()

        # Worker loops are best-effort background services. Shutdown must remain bounded
        # so a slow provider/Kubernetes/database call cannot indefinitely hold a pod in
        # Terminating and block a local or production rollout.
        done, pending = await asyncio.wait(
            tasks, timeout=WORKER_SHUTDOWN_TIMEOUT_SECONDS
        )
        for task in done:
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Background worker failed during shutdown")
        for task in pending:
            logger.error(
                "Background worker %s did not stop within %.1f seconds; cancellation was reissued",
                task.get_name(),
                WORKER_SHUTDOWN_TIMEOUT_SECONDS,
            )
            task.cancel()


settings = get_settings()
expected_release = os.getenv("DCV_EXPECTED_RELEASE")
if expected_release and expected_release != settings.app_version:
    raise RuntimeError(f"DCV release mismatch: expected {expected_release}, loaded {settings.app_version}")

app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

@app.get("/api/build-info")
def build_info():
    return {"version": settings.app_version, "service": settings.app_name}
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
app.include_router(admin_router, prefix="/api/admin")
app.include_router(billing_router, prefix="/api/billing")
app.include_router(webhook_router, prefix="/webhooks")
