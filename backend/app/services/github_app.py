from __future__ import annotations
import asyncio, base64, hashlib, hmac, time
from datetime import datetime, timezone
from urllib.parse import quote
import httpx, jwt
from app.config import get_settings


def github_configured() -> bool:
    s = get_settings(); return bool(s.github_app_id and s.normalized_private_key and s.github_webhook_secret)


def verify_signature(body: bytes, signature: str | None) -> bool:
    s = get_settings(); secret = s.github_webhook_secret
    if not secret or not signature or not signature.startswith("sha256="): return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def app_jwt() -> str:
    s = get_settings()
    if not s.github_app_id or not s.normalized_private_key: raise RuntimeError("GitHub App is not configured")
    now = int(time.time())
    return jwt.encode({"iat": now - 30, "exp": now + 540, "iss": int(s.github_app_id)}, s.normalized_private_key, algorithm="RS256")


def _headers(token: str) -> dict[str, str]:
    s = get_settings(); return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": s.github_api_version, "User-Agent": "Dependency-Change-Verification/10.0"}


async def _request(method: str, path: str, token: str, **kwargs) -> httpx.Response:
    s = get_settings()
    for attempt in range(s.github_max_retries + 1):
        try:
            async with httpx.AsyncClient(base_url=s.github_api_url, timeout=s.github_request_timeout_seconds) as client:
                response = await client.request(method, path, headers=_headers(token), **kwargs)
            if response.status_code in {429, 502, 503, 504} and attempt < s.github_max_retries:
                retry_after = response.headers.get("Retry-After")
                try: delay = float(retry_after) if retry_after else 2 ** attempt
                except ValueError: delay = 2 ** attempt
                await asyncio.sleep(min(delay, 30)); continue
            response.raise_for_status(); return response
        except (httpx.HTTPError, OSError):
            if attempt >= s.github_max_retries: raise
            await asyncio.sleep(min(2 ** attempt, 15))
    raise RuntimeError("GitHub request failed")


async def installation_token(installation_id: int, repository: str | None = None) -> str:
    payload = {}
    if repository and "/" in repository:
        payload = {"repositories": [repository.split("/", 1)[1]], "permissions": {"contents": "read", "pull_requests": "read", "checks": "write", "issues": "write"}}
    return (await _request("POST", f"/app/installations/{installation_id}/access_tokens", app_jwt(), json=payload or None)).json()["token"]

async def get_app() -> dict:
    return (await _request("GET", "/app", app_jwt())).json()

async def get_installation(installation_id: int) -> dict:
    return (await _request("GET", f"/app/installations/{installation_id}", app_jwt())).json()


async def list_installations() -> list[dict]:
    return (await _request("GET", "/app/installations", app_jwt(), params={"per_page": 100})).json()

async def list_installation_repositories(token: str) -> list[dict]:
    return (await _request("GET", "/installation/repositories", token, params={"per_page": 100})).json().get("repositories", [])

async def list_pr_files(token: str, repo: str, pr_number: int) -> list[dict]:
    out=[]
    for page in range(1,11):
        chunk=(await _request("GET", f"/repos/{repo}/pulls/{pr_number}/files", token, params={"per_page":100,"page":page})).json()
        if not chunk: break
        out.extend(chunk)
        if len(chunk)<100: break
    return out

async def get_content(token: str, repo: str, path: str, ref: str) -> str:
    data=(await _request("GET", f"/repos/{repo}/contents/{quote(path,safe='/')}", token, params={"ref":ref})).json()
    if isinstance(data,list) or data.get("encoding")!="base64": raise RuntimeError(f"GitHub did not return file content for {path}")
    return base64.b64decode(data["content"]).decode("utf-8",errors="replace")

async def create_check(token: str, repo: str, head_sha: str, name: str, summary: str, details_url: str | None=None) -> int:
    payload={"name":name,"head_sha":head_sha,"status":"in_progress","started_at":datetime.now(timezone.utc).isoformat(),"output":{"title":"Verification running","summary":summary}}
    if details_url: payload["details_url"]=details_url
    return int((await _request("POST",f"/repos/{repo}/check-runs",token,json=payload)).json()["id"])

async def update_check(token: str, repo: str, check_run_id: int, conclusion: str, title: str, summary: str, text: str="", details_url: str|None=None) -> None:
    payload={"status":"completed","completed_at":datetime.now(timezone.utc).isoformat(),"conclusion":conclusion,"output":{"title":title,"summary":summary,"text":text[:65000]}}
    if details_url: payload["details_url"]=details_url
    await _request("PATCH",f"/repos/{repo}/check-runs/{check_run_id}",token,json=payload)

async def list_issue_comments(token: str, repo: str, issue_number: int) -> list[dict]:
    out=[]
    for page in range(1,11):
        chunk=(await _request("GET",f"/repos/{repo}/issues/{issue_number}/comments",token,params={"per_page":100,"page":page})).json()
        if not chunk: break
        out.extend(chunk)
        if len(chunk)<100: break
    return out

async def upsert_pr_comment(token: str, repo: str, pr_number: int, marker: str, body: str) -> int:
    for comment in await list_issue_comments(token, repo, pr_number):
        if marker in (comment.get("body") or ""):
            return int((await _request("PATCH",f"/repos/{repo}/issues/comments/{comment['id']}",token,json={"body":body})).json()["id"])
    return int((await _request("POST",f"/repos/{repo}/issues/{pr_number}/comments",token,json={"body":body})).json()["id"])


async def find_check(token: str, repo: str, head_sha: str, name: str) -> int | None:
    data = (await _request("GET", f"/repos/{repo}/commits/{head_sha}/check-runs", token, params={"check_name": name, "per_page": 100})).json()
    runs = data.get("check_runs") or []
    for run in runs:
        if run.get("name") == name:
            return int(run["id"])
    return None
