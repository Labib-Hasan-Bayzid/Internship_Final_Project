from __future__ import annotations

import json
from openai import OpenAI
from app.config import get_settings


def ai_configured() -> bool:
    settings = get_settings()
    return bool(settings.ai_enabled and settings.openai_api_key)


def fallback_explanation(package_name: str, old_version: str, new_version: str, comparison: dict) -> str:
    return (
        f"Deterministic verification summary for {package_name} {old_version} → {new_version}.\n\n"
        f"What changed\n{comparison.get('reason', 'Verification completed.')}\n\n"
        f"Decision\n{comparison.get('decision', 'REVIEW')} ({comparison.get('severity', 'UNKNOWN')}).\n\n"
        "AI is not configured. Set AI_ENABLED=true and OPENAI_API_KEY to enable evidence-based AI explanations."
    )


def explain_result(package_name: str, old_version: str, new_version: str, evidence: dict, allow_fallback: bool = True) -> str:
    settings = get_settings()
    comparison = evidence.get("comparison") or {}
    fallback = fallback_explanation(package_name, old_version, new_version, comparison)
    if not ai_configured():
        return fallback

    prompt = f"""You are the explanation layer of Dependency Change Verification (DCV).
The deterministic engine already decided the gate. Your job is to explain the supplied evidence to a software engineer.
Use only the evidence supplied below. Never invent facts. Never override the deterministic decision.
Do not claim a dependency is safe, malicious, vulnerable, compromised, or trustworthy unless that exact fact is present in evidence.
Keep the explanation concise and evidence-based.
Return exactly these headings:
What changed
Why it matters
Recommended action

Package: {package_name}
Old version: {old_version}
New version: {new_version}
Evidence:
{json.dumps(evidence, indent=2, default=str)[:50000]}
"""
    try:
        client = OpenAI(api_key=settings.openai_api_key, timeout=30.0)
        response = client.responses.create(model=settings.ai_model, input=prompt, store=False)
        text = (response.output_text or "").strip()
        return text or fallback
    except Exception as exc:
        if not allow_fallback:
            raise
        return fallback + f"\n\nAI provider failure was contained without changing the deterministic decision: {type(exc).__name__}."


def test_ai_connection() -> str:
    settings = get_settings()
    if not ai_configured():
        raise RuntimeError("AI is not configured")
    client = OpenAI(api_key=settings.openai_api_key, timeout=20.0)
    response = client.responses.create(model=settings.ai_model, input="Reply exactly: DCV AI connection OK.", store=False)
    return (response.output_text or "").strip()
