import json
import sys
import os
import hmac
import hashlib
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
import httpx

from app.core.config import GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_WEBHOOK_SECRET_KEY, BACKEND_URL, FRONTEND_URL
from app.utils.websocket_manager import manager
from app.services.github_service import generate_user_webhook_secret, register_github_webhook
from app.services.oauth_service import save_unified_user_profile, get_frontend_url
from app.services.event_service import process_and_save
from state_machine import process_normalized_event
import asyncio

router = APIRouter()


@router.post("/webhook/github")
async def receive_github(request: Request):
    github_event = request.headers.get("X-GitHub-Event", "unknown")
    raw_body = await request.body()
    github_signature = request.headers.get("X-Hub-Signature-256", "")

    # ── SIGNATURE VERIFICATION ─────────────────────────────────
    # Step 1: Read GITHUB_WEBHOOK_SECRET_KEY from environment
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET_KEY", "") or GITHUB_WEBHOOK_SECRET_KEY or ""

    # Step 2: If GITHUB_WEBHOOK_SECRET_KEY is set AND is not "default_secret" AND is not empty
    if webhook_secret and webhook_secret != "default_secret" and webhook_secret.strip() != "":
        if not github_signature:
            print("[GITHUB] ❌ Rejected — missing signature header")
            sys.stdout.flush()
            return JSONResponse(
                status_code=401,
                content={"error": "Missing signature header. Request rejected."}
            )

        expected_signature = (
            "sha256="
            + hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(github_signature, expected_signature):
            print("[GITHUB] ❌ Rejected — invalid signature")
            sys.stdout.flush()
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid signature. Request rejected."}
            )

        print("[GITHUB] ✅ Signature verified")
        sys.stdout.flush()
    else:
        # Step 3: If GITHUB_WEBHOOK_SECRET_KEY is NOT set or is "default_secret"
        print("[GITHUB] ⚠️ WARNING — No webhook secret configured.\nAccepting request without verification.\nSet GITHUB_WEBHOOK_SECRET_KEY in environment.")
        sys.stdout.flush()
    # ── END SIGNATURE VERIFICATION ──────────────────────────────

    # Handle ping event
    if github_event == "ping":
        print("[GITHUB] ✅ Ping received — webhook registered successfully!")
        sys.stdout.flush()
        return {"received": True, "message": "Ping acknowledged"}

    # Parse payload
    try:
        payload = json.loads(raw_body)
    except Exception:
        return {"error": "Invalid JSON payload"}

    # Find out who sent this event
    sender = (
        payload.get("sender", {}).get("login")
        or payload.get("pusher", {}).get("name")
        or "unknown"
    )

    from app.services.event_service import log_webhook_payload
    log_webhook_payload("GITHUB", payload)

    # ── NORMALIZE EVENT FIRST ──────────────────────────────────
    normalized = process_and_save("github", github_event, payload)

    # ── WEBSOCKET BROADCAST: New Event ─────────────────────────
    # Broadcast every new event to the frontend feed
    asyncio.create_task(
        manager.broadcast({"type": "new_event", **normalized.model_dump()})
    )

    # ── SMART STATE MACHINE ────────────────────────────────────
    updated_tasks = []

    # Pass the normalized dict straight to the engine (now async)
    state_change = await process_normalized_event(normalized.model_dump())

    if state_change:
        # A state transition successfully happened!
        updated_tasks.append(state_change["id"])

        # Get the old and new status from the history trail
        last_transition = state_change["history"][-1] if state_change["history"] else {}
        old_status = (
            last_transition.get("from", "UPCOMING").lower()
            if last_transition.get("from") != "UPCOMING"
            else "upcoming"
        )
        new_status = state_change["status"]

        # ── WEBSOCKET BROADCAST ────────────────────────────────
        try:
            asyncio.create_task(
                manager.broadcast(
                    {
                        "type": "task_updated",
                        "task_id": state_change["id"],
                        "old_status": old_status,
                        "new_status": new_status,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            print(f"[WEBSOCKET] 📡 Broadcast triggered for {state_change['id']}")
            sys.stdout.flush()
        except Exception as e:
            print(f"[WEBSOCKET] ⚠️ Broadcast failed: {e}")
            sys.stdout.flush()

    return {
        "received": True,
        "platform": "github",
        "event_type": github_event,
        "sender": sender,
        "normalized_summary": normalized.action_summary,
        "tasks_auto_updated": updated_tasks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/auth/github")
async def github_login(request: Request, repo: Optional[str] = None, user_id: Optional[str] = None, return_url: Optional[str] = None):
    actual_return = get_frontend_url(request, return_url)

    # We pass the repo name and user_id through GitHub's "state" parameter
    # GitHub preserves "state" through the OAuth flow and sends it back
    state_dict = {}
    if repo:
        state_dict["repo"] = repo
    if user_id:
        state_dict["user_id"] = user_id
    if actual_return != FRONTEND_URL:
        state_dict["return_url"] = actual_return
        
    state = urllib.parse.quote(json.dumps(state_dict)) if state_dict else ""

    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&scope=read:user,repo,admin:repo_hook"
        f"&state={state}"
        f"&redirect_uri={os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/github/callback"
    )
    return RedirectResponse(github_auth_url)


@router.get("/auth/github/callback")
async def github_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None, error_description: Optional[str] = None):
    frontend_url = FRONTEND_URL
    
    repo = None
    existing_user_id = None
    if state:
        try:
            state_dict = json.loads(urllib.parse.unquote(state))
            if isinstance(state_dict, dict):
                repo = state_dict.get("repo")
                existing_user_id = state_dict.get("user_id")
                if state_dict.get("return_url"):
                    frontend_url = state_dict.get("return_url")
            else:
                repo = urllib.parse.unquote(state)
        except Exception:
            # Fallback for old simple string state
            repo = urllib.parse.unquote(state)

    if error or not code:
        err_msg = error_description or error or "missing_code"
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error={err_msg}")

    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        print("[GITHUB AUTH] ❌ Missing GitHub client credentials.")
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error=server_error")

    async with httpx.AsyncClient() as client:
        # Step 1 — Exchange code for access token
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/github/callback",
            },
            headers={"Accept": "application/json"},
        )
        try:
            token_data = token_response.json()
        except ValueError:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error=provider_error")

        access_token = token_data.get("access_token")

        if not access_token:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error=failed_to_get_token")

        # Step 2 — Get user's GitHub profile
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        try:
            user_data = user_response.json()
        except ValueError:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error=provider_error")

        github_username = user_data.get("login")

    # Step 3 — Auto register webhook on their repo
    # State parameter was decoded at the top of the function

    webhook_result = {"success": False, "note": "No repo provided"}

    user_profile = save_unified_user_profile(
        github_username=github_username, 
        github_access_token=access_token,
        github_repo=repo,
        existing_user_id=existing_user_id
    )
    user_id = user_profile.get("user_id") if user_profile else ""
    is_new_user = user_profile.get("is_new_user", True) if user_profile else True

    if repo:
        print(f"[GITHUB] Registering webhook for {github_username} on {repo}")
        sys.stdout.flush()
        webhook_result = await register_github_webhook(
            access_token=access_token,
            github_username=github_username,
            repo_full_name=repo,
        )

    redirect_url = f"{frontend_url}/oauth/callback?platform=github&username={github_username}&user_id={user_id}"
    if is_new_user:
        redirect_url += "&isNewUser=true"
    return RedirectResponse(url=redirect_url)


@router.get("/connected-users")
async def get_connected_users():
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import PlatformIntegrationTable

    db = SessionLocal()
    try:
        db_users = db.query(PlatformIntegrationTable).filter_by(platform_name="github").all()
        safe_users = []
        for u in db_users:
            meta = u.platform_metadata or {}
            safe_users.append(
                {
                    "github_username": meta.get("username"),
                    "repo": meta.get("repo"),
                    "connected_at": u.connected_at,
                    "webhook_registered": True, # Hardcoded assuming registered if present
                    "webhook_id": meta.get("webhook_id"),
                }
            )
        result = {"total": len(safe_users), "connected_users": safe_users}
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()
