import os
import sys
import json
import urllib.parse
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response, JSONResponse
import httpx
import asyncio

from app.core.config import DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, FRONTEND_URL
from app.services.oauth_service import save_unified_user_profile, get_frontend_url
from app.services.event_service import process_and_save, log_webhook_payload
from app.services.standup_service import run_daily_standup

router = APIRouter()


@router.post("/webhook/discord")
async def receive_discord(request: Request):
    payload = await request.json()
    log_webhook_payload("DISCORD", payload)
    if payload.get("type") == 1:
        print("[DISCORD] Verification ping — responding with handshake.")
        sys.stdout.flush()
        return {"type": 1}
    normalized = process_and_save("discord", "discord_message", payload)
    return {
        "received": True,
        "platform": "discord",
        "normalized_summary": normalized.action_summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/auth/discord")
async def discord_login(request: Request, user_id: Optional[str] = None, return_url: Optional[str] = None):
    actual_return = get_frontend_url(request, return_url)

    state_dict = {}
    if user_id:
        state_dict["user_id"] = user_id
    if actual_return != FRONTEND_URL:
        state_dict["return_url"] = actual_return

    state = urllib.parse.quote(json.dumps(state_dict)) if state_dict else ""

    discord_auth_url = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/discord/callback"
        f"&response_type=code"
        f"&scope=identify%20email%20guilds"
        f"&state={state}"
    )
    return RedirectResponse(discord_auth_url)


@router.get("/auth/discord/callback")
async def discord_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None, error_description: Optional[str] = None):
    frontend_url = FRONTEND_URL
    
    existing_user_id = None
    if state:
        try:
            state_dict = json.loads(urllib.parse.unquote(state))
            if isinstance(state_dict, dict):
                existing_user_id = state_dict.get("user_id")
                if state_dict.get("return_url"):
                    frontend_url = state_dict.get("return_url")
            else:
                existing_user_id = urllib.parse.unquote(state)
        except Exception:
            existing_user_id = urllib.parse.unquote(state)

    if error or not code:
        err_msg = error_description or error or "missing_code"
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error={err_msg}")

    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        print("[DISCORD AUTH] ❌ Missing Discord client credentials.")
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error=server_error")

    async with httpx.AsyncClient() as client:
        # Step 1 — Exchange code for access token
        token_response = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/discord/callback",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            token_data = token_response.json()
        except ValueError:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error=provider_error")

        access_token = token_data.get("access_token")

        if not access_token:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error=failed_to_get_token")

        # Step 2 — Use token to get user's Discord profile
        user_response = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            user_data = user_response.json()
        except ValueError:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error=provider_error")

        discord_id = user_data.get("id")
        discord_username = user_data.get("username")
        email = user_data.get("email")

    # Step 3 — Save this user to our records
    user_profile = save_unified_user_profile(
        discord_id=discord_id,
        discord_username=discord_username,
        discord_access_token=access_token,
        email=email,
        existing_user_id=existing_user_id
    )
    user_id = user_profile.get("user_id") if user_profile else ""
    is_new_user = user_profile.get("is_new_user", True) if user_profile else True

    redirect_url = f"{frontend_url}/oauth/callback?platform=discord&username={discord_username}&user_id={user_id}"
    if is_new_user:
        redirect_url += "&isNewUser=true"
    return RedirectResponse(url=redirect_url)


@router.get("/discord-users")
async def get_discord_users():
    from database import SessionLocal
    from models_sql import PlatformIntegrationTable, UserTable

    db = SessionLocal()
    try:
        db_users = db.query(PlatformIntegrationTable, UserTable)\
                     .join(UserTable, PlatformIntegrationTable.user_id == UserTable.id)\
                     .filter(PlatformIntegrationTable.platform_name == "discord").all()
        
        safe_users = []
        for pi, user in db_users:
            meta = pi.platform_metadata or {}
            safe_users.append(
                {
                    "discord_id": meta.get("discord_id"),
                    "discord_username": meta.get("username"),
                    "email": user.email,
                    "connected_at": pi.connected_at,
                }
            )
        result = {"total": len(safe_users), "discord_users": safe_users}
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()


@router.get("/discord/activity")
async def get_discord_activity():
    filepath = "discord_activity.json"

    if not os.path.exists(filepath):
        return {"total_members": 0, "activity": []}

    with open(filepath, "r") as f:
        activity = json.load(f)

    summary = []
    for actor, data in activity.items():
        summary.append(
            {
                "member": actor,
                "currently_working_on": data.get("latest_message", "No recent updates"),
                "last_seen": data.get("last_seen", "unknown"),
                "total_messages": data.get("message_count", 0),
            }
        )

    result = {
        "total_members_active": len(summary),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "team_activity": summary,
    }

    formatted = json.dumps(result, indent=4)
    return Response(content=formatted, media_type="application/json")


@router.get("/test/standup")
async def test_standup():
    print("[TEST] Manually triggering standup...")
    sys.stdout.flush()
    await run_daily_standup()
    return {
        "message": "Standup triggered manually",
        "check": "Your Discord DMs for the standup message",
    }


@router.get("/test-daily-standup")
async def test_daily_standup():
    # Manually triggers the daily standup routine in the background.
    asyncio.create_task(run_daily_standup())
    return {"status": "success", "message": "Daily standup triggered in background."}
