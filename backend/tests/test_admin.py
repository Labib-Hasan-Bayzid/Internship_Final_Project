from inspect import signature
from fastapi.params import Depends as DependsParam
from app.api.admin import accept_invitation, members, audit_logs, create_organization, context as admin_context
from app.api.routes import normalize_repository
from fastapi import HTTPException
from app.services.tenant import actor_user, actor_context
from app.database import get_db


def test_admin_routes_use_db_dependencies():
    assert isinstance(signature(members).parameters["db"].default, DependsParam)
    assert signature(members).parameters["db"].default.dependency is get_db
    assert isinstance(signature(accept_invitation).parameters["user"].default, DependsParam)
    assert signature(accept_invitation).parameters["user"].default.dependency is actor_user
    assert isinstance(signature(actor_context).parameters["db"].default, DependsParam)


def test_repository_normalization():
    assert normalize_repository("https://github.com/acme/payments/") == "https://github.com/acme/payments"
    try:
        normalize_repository("http://github.com/acme/payments")
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("Expected repository validation failure")


def test_first_org_context_and_creation_use_actor_identity():
    assert isinstance(signature(admin_context).parameters["user"].default, DependsParam)
    assert signature(admin_context).parameters["user"].default.dependency is actor_user
    assert isinstance(signature(create_organization).parameters["user"].default, DependsParam)
    assert signature(create_organization).parameters["user"].default.dependency is actor_user
