import hashlib
import hmac

from app.api.routes import github_conclusion
from app.config import get_settings
from app.services.github_app import verify_signature


def test_github_conclusions():
    assert github_conclusion("PASS") == "success"
    assert github_conclusion("REVIEW") == "action_required"
    assert github_conclusion("BLOCK") == "failure"


def test_github_webhook_signature(monkeypatch):
    secret = "unit-test-secret"
    body = b'{"action":"opened"}'
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, signature)
    assert not verify_signature(body, signature[:-1] + "0")
    get_settings.cache_clear()
