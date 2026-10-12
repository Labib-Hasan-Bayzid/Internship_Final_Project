from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Dependency Change Verification"
    app_version: str = "15.0.0"
    environment: str = "production"
    app_public_url: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://dcv:dcv@localhost:5432/dcv"
    cors_origins: str = "http://localhost:3000"

    k8s_enabled: bool = True
    k8s_namespace: str = "dcv-runs"
    k8s_job_timeout_seconds: int = 600
    runner_image_python: str = "dcv-runner-python:15.0.0-local"
    runner_image_node: str = "dcv-runner-node:15.0.0-local"

    ai_enabled: bool = False
    ai_auto_explain: bool = True
    ai_model: str = "gpt-5"
    openai_api_key: str | None = None
    ai_max_attempts: int = 3

    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2026-03-10"
    github_app_id: str | None = None
    github_app_slug: str | None = None
    github_private_key: str | None = None
    github_webhook_secret: str | None = None
    github_auto_verify: bool = True
    github_pr_comments: bool = True
    github_request_timeout_seconds: float = 30.0
    github_max_retries: int = 3
    webhook_max_attempts: int = 6
    webhook_stale_minutes: int = 10
    webhook_poll_seconds: float = 2.0
    reconcile_stale_minutes: int = 10
    github_publish_stale_minutes: int = 10
    billing_max_attempts: int = 6
    billing_stale_minutes: int = 10
    billing_poll_seconds: float = 5.0

    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_team: str | None = None
    stripe_price_business: str | None = None
    stripe_success_url: str | None = None
    stripe_cancel_url: str | None = None
    billing_portal_return_url: str | None = None

    dev_identity_email: str = "owner@local.dcv"
    dev_identity_name: str = "Local Owner"
    dev_identity_bootstrap: bool = True
    default_org_name: str = "Local Organization"
    default_org_slug: str = "local"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def normalized_private_key(self) -> str | None:
        return self.github_private_key.replace("\\n", "\n") if self.github_private_key else None

    @property
    def github_webhook_url(self) -> str:
        return self.app_public_url.rstrip("/") + "/webhooks/github"

    @property
    def github_setup_url(self) -> str:
        return self.app_public_url.rstrip("/") + "/api/github/setup"

    @property
    def github_install_url(self) -> str | None:
        return f"https://github.com/apps/{self.github_app_slug}/installations/new" if self.github_app_slug else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
