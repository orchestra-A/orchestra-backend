import os
import sys
import json
import urllib.parse
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
import httpx

from app.core.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, FRONTEND_URL
from app.services.oauth_service import save_unified_user_profile, get_frontend_url

router = APIRouter()


@router.get("/auth/google")
async def google_login(request: Request, user_id: Optional[str] = None, return_url: Optional[str] = None):
    actual_return = get_frontend_url(request, return_url)

    state_dict = {}
    if user_id:
        state_dict["user_id"] = user_id
    if actual_return != FRONTEND_URL:
        state_dict["return_url"] = actual_return

    # Pass state so we can link to existing profile and redirect correctly
    state = urllib.parse.quote(json.dumps(state_dict)) if state_dict else ""

    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/google/callback"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
        f"&state={state}"
    )
    return RedirectResponse(google_auth_url)


@router.get("/auth/google/callback")
async def google_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None, error_description: Optional[str] = None):
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
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=google&error={err_msg}")

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        print("[GOOGLE AUTH] ❌ Missing Google client credentials.")
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=google&error=server_error")

    async with httpx.AsyncClient() as client:
        # Step 1 — Exchange code for access token
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/google/callback"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        try:
            token_data = token_response.json()
        except ValueError:
            return RedirectResponse(
                url=f"{frontend_url}/oauth/callback?platform=google&error=provider_error"
            )

        access_token = token_data.get("access_token")

        if not access_token:
            print(f"[GOOGLE AUTH] ❌ Failed to get token: {token_data}")
            sys.stdout.flush()
            return RedirectResponse(
                url=f"{frontend_url}/oauth/callback?platform=google&error=failed_to_get_token"
            )

        # Step 2 — Use token to get user's Google profile
        user_response = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        try:
            user_data = user_response.json()
        except ValueError:
            return RedirectResponse(
                url=f"{frontend_url}/oauth/callback?platform=google&error=provider_error"
            )

    google_id = user_data.get("id")
    email = user_data.get("email")
    name = user_data.get("name")
    picture = user_data.get("picture")

    print(f"[GOOGLE AUTH] ✅ User logged in: {email} ({name})")
    sys.stdout.flush()

    # Step 3 — Get existing user_id from state if linking accounts
    # Step 4 — Save to unified user profile (links to any existing GitHub/Discord profile)
    user_profile = save_unified_user_profile(
        email=email,
        existing_user_id=existing_user_id,
        google_id=google_id,
        google_name=name,
        google_picture=picture,
        google_access_token=access_token
    )

    user_id = user_profile.get("user_id") if user_profile else ""
    is_new_user = user_profile.get("is_new_user", True) if user_profile else True

    # Step 5 — Redirect back to frontend with user info
    redirect_url = (
        f"{frontend_url}/oauth/callback"
        f"?platform=google"
        f"&email={urllib.parse.quote(email or '')}"
        f"&name={urllib.parse.quote(name or '')}"
        f"&user_id={user_id}"
        f"&picture={urllib.parse.quote(picture or '')}"
    )
    if is_new_user:
        redirect_url += "&isNewUser=true"

    return RedirectResponse(url=redirect_url)


@router.get("/google-users")
async def get_google_users():
    from database import SessionLocal
    from models_sql import PlatformIntegrationTable, UserTable

    db = SessionLocal()
    try:
        db_users = db.query(PlatformIntegrationTable, UserTable)\
                     .join(UserTable, PlatformIntegrationTable.user_id == UserTable.id)\
                     .filter(PlatformIntegrationTable.platform_name == "google").all()

        safe_users = []
        for pi, user in db_users:
            meta = pi.platform_metadata or {}
            
            # Check for other integrations
            other_pis = db.query(PlatformIntegrationTable).filter(PlatformIntegrationTable.user_id == user.id).all()
            github_username = None
            discord_username = None
            for opi in other_pis:
                if opi.platform_name == "github":
                    github_username = (opi.platform_metadata or {}).get("username")
                elif opi.platform_name == "discord":
                    discord_username = (opi.platform_metadata or {}).get("username")

            safe_users.append({
                "user_id": user.id,
                "email": user.email,
                "google_name": meta.get("name"),
                "google_picture": meta.get("picture"),
                "github_username": github_username,
                "discord_username": discord_username,
                "connected_at": pi.connected_at
            })

        result = {
            "total": len(safe_users),
            "google_users": safe_users
        }
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()


@router.get("/users")
async def get_users():
    from database import SessionLocal
    from models_sql import UserTable, PlatformIntegrationTable

    db = SessionLocal()
    try:
        db_users = db.query(UserTable).all()
        safe_profiles = []
        for u in db_users:
            # Get integrations for this user
            integrations = db.query(PlatformIntegrationTable).filter_by(user_id=u.id).all()
            platforms_connected = [pi.platform_name for pi in integrations]
            
            # Find specific usernames for backwards compatibility
            gh = next((pi for pi in integrations if pi.platform_name == "github"), None)
            dc = next((pi for pi in integrations if pi.platform_name == "discord"), None)
            
            safe_profiles.append(
                {
                    "user_id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "github_username": gh.platform_metadata.get("username") if gh and gh.platform_metadata else None,
                    "discord_username": dc.platform_metadata.get("username") if dc and dc.platform_metadata else None,
                    "discord_id": dc.platform_metadata.get("discord_id") if dc and dc.platform_metadata else None,
                    "platforms_connected": platforms_connected,
                    "created_at": u.created_at,
                    "updated_at": u.updated_at,
                    "skills": u.skills if u.skills is not None else [],
                }
            )
        result = {"total": len(safe_profiles), "users": safe_profiles}
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()


@router.get("/users/{user_id}")
async def get_user_by_id(user_id: str):
    from database import SessionLocal
    from models_sql import UserTable, PlatformIntegrationTable

    db = SessionLocal()
    try:
        u = db.query(UserTable).filter_by(id=user_id).first()
        if not u:
            return Response(content='{"error": "User not found"}', media_type="application/json", status_code=404)
        
        # Get integrations for this user
        integrations = db.query(PlatformIntegrationTable).filter_by(user_id=u.id).all()
        platforms_connected = [pi.platform_name for pi in integrations]
        
        # Find specific usernames
        gh = next((pi for pi in integrations if pi.platform_name == "github"), None)
        dc = next((pi for pi in integrations if pi.platform_name == "discord"), None)
        
        profile = {
            "user_id": u.id,
            "username": u.username,
            "email": u.email,
            "github_username": gh.platform_metadata.get("username") if gh and gh.platform_metadata else None,
            "discord_username": dc.platform_metadata.get("username") if dc and dc.platform_metadata else None,
            "discord_id": dc.platform_metadata.get("discord_id") if dc and dc.platform_metadata else None,
            "platforms_connected": platforms_connected,
            "created_at": u.created_at,
            "updated_at": u.updated_at,
            "skills": u.skills if u.skills is not None else [],
        }
        
        return Response(content=json.dumps(profile, indent=4), media_type="application/json")
    except Exception as e:
        print(f"[AUTH] Error fetching user {user_id}: {e}")
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)
    finally:
        db.close()



@router.put("/users/{user_id}")
async def update_user_put(user_id: str, payload: dict):
    from database import SessionLocal
    from models_sql import UserTable

    db = SessionLocal()
    try:
        user = db.query(UserTable).filter_by(id=user_id).first()
        if not user:
            return Response(content='{"error": "User not found"}', media_type="application/json", status_code=404)
        
        data = payload
        if "username" in data:
            user.username = data["username"]
        if "name" in data:
            user.name = data["name"]
        if "email" in data:
            user.email = data["email"]
        if "skills" in data:
            user.skills = data["skills"]
        
        user.updated_at = datetime.now(timezone.utc).isoformat()
        db.commit()
        return Response(content='{"message": "User updated successfully"}', media_type="application/json")
    finally:
        db.close()


@router.patch("/users/{user_id}")
async def update_user_patch(user_id: str, payload: dict):
    from database import SessionLocal
    from models_sql import UserTable

    db = SessionLocal()
    try:
        user = db.query(UserTable).filter_by(id=user_id).first()
        if not user:
            return Response(content='{"error": "User not found"}', media_type="application/json", status_code=404)
        
        data = payload
        if "username" in data:
            user.username = data["username"]
        if "name" in data:
            user.name = data["name"]
        if "email" in data:
            user.email = data["email"]
        if "skills" in data:
            user.skills = data["skills"]
        
        user.updated_at = datetime.now(timezone.utc).isoformat()
        db.commit()
        return Response(content='{"message": "User patched successfully"}', media_type="application/json")
    finally:
        db.close()
