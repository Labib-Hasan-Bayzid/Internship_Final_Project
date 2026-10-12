from inspect import signature
from fastapi.params import Depends as DependsParam
from app.services.tenant import PLANS, actor_context
from app.database import get_db

def test_plan_catalog_has_expected_entitlements():
    assert PLANS["FREE"]["verification_runs"] == 50
    assert PLANS["TEAM"]["projects"] == 25
    assert PLANS["BUSINESS"]["ai_explanations"] == 20000
    assert PLANS["ENTERPRISE"]["verification_runs"] == -1


def test_actor_context_uses_fastapi_db_dependency():
    assert isinstance(signature(actor_context).parameters["db"].default, DependsParam)
    assert getattr(signature(actor_context).parameters["db"].default, "dependency", None) is get_db
