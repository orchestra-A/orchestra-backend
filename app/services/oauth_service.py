from datetime import datetime, timezone
from typing import Optional
from app.core.config import FRONTEND_URL

def save_discord_user(
    discord_id: str, discord_username: str, access_token: str, email: Optional[str] = None
) -> None:
    # Saves a Discord connected user to the database.
    save_unified_user_profile(
        discord_id=discord_id,
        discord_username=discord_username,
        discord_access_token=access_token,
        email=email
    )


def save_unified_user_profile(
    github_username: Optional[str] = None,
    github_access_token: Optional[str] = None,
    discord_id: Optional[str] = None,
    discord_username: Optional[str] = None,
    discord_access_token: Optional[str] = None,
    email: Optional[str] = None,
    github_repo: Optional[str] = None,
    existing_user_id: Optional[str] = None,
    google_id: Optional[str] = None,
    google_name: Optional[str] = None,
    google_picture: Optional[str] = None,
    google_access_token: Optional[str] = None,
) -> dict:
    # Creates or updates a unified user profile in the database using the dynamic PlatformIntegration table.
    from database import SessionLocal
    from models_sql import UserTable, PlatformIntegrationTable
    from sqlalchemy.orm.attributes import flag_modified
    from sqlalchemy.exc import OperationalError
    import uuid
    import time
    import sys

    retries = 3
    for attempt in range(retries):
        db = SessionLocal()
        try:
            # 1. Find or create UserTable
            user = None
            if existing_user_id:
                user = db.query(UserTable).filter_by(id=existing_user_id).first()
            if not user and email:
                user = db.query(UserTable).filter(UserTable.email.ilike(email.strip())).first()
            if not user and github_username:
                user = db.query(UserTable).filter(UserTable.username.ilike(github_username.strip())).first()
                if not user:
                    # Search by GitHub integration metadata
                    pi = db.query(PlatformIntegrationTable).filter_by(platform_name="github").all()
                    for item in pi:
                        meta = item.platform_metadata or {}
                        if meta.get("username", "").lower() == github_username.strip().lower():
                            user = db.query(UserTable).filter_by(id=item.user_id).first()
                            if user:
                                break
            if not user and discord_username:
                user = db.query(UserTable).filter(UserTable.username.ilike(discord_username.strip())).first()
                if not user:
                    # Search by Discord integration metadata
                    pi = db.query(PlatformIntegrationTable).filter_by(platform_name="discord").all()
                    for item in pi:
                        meta = item.platform_metadata or {}
                        if meta.get("username", "").lower() == discord_username.strip().lower() or meta.get("discord_id") == discord_id:
                            user = db.query(UserTable).filter_by(id=item.user_id).first()
                            if user:
                                break
            if not user and google_id:
                # Search by Google integration metadata
                pi = db.query(PlatformIntegrationTable).filter_by(platform_name="google").all()
                for item in pi:
                    meta = item.platform_metadata or {}
                    if meta.get("google_id") == google_id:
                        user = db.query(UserTable).filter_by(id=item.user_id).first()
                        if user:
                            break

            if not user:
                user_id = f"usr_{str(uuid.uuid4())[:8]}"
                primary_username = github_username or discord_username or (email.split("@")[0] if email else f"user_{str(uuid.uuid4())[:4]}")
                user = UserTable(
                    id=user_id,
                    username=primary_username,
                    email=email,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    skills=[]
                )
                db.add(user)
                db.flush() # get user.id so we can use it for foreign keys
    
            # 2. Upsert GitHub PlatformIntegration
            if github_username:
                pi_gh = db.query(PlatformIntegrationTable).filter_by(platform_name="github", user_id=user.id).first()
                if not pi_gh:
                    pi_gh = PlatformIntegrationTable(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        platform_name="github",
                        connected_at=datetime.now(timezone.utc).isoformat()
                    )
                    db.add(pi_gh)
                pi_gh.access_token = github_access_token
                meta = dict(pi_gh.platform_metadata) if pi_gh.platform_metadata else {}
                meta["username"] = github_username
                if github_repo:
                    meta["repo"] = github_repo
                pi_gh.platform_metadata = meta
                flag_modified(pi_gh, "platform_metadata")
    
            # 3. Upsert Discord PlatformIntegration
            if discord_id:
                pi_dc = db.query(PlatformIntegrationTable).filter_by(platform_name="discord", user_id=user.id).first()
                if not pi_dc:
                    pi_dc = PlatformIntegrationTable(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        platform_name="discord",
                        connected_at=datetime.now(timezone.utc).isoformat()
                    )
                    db.add(pi_dc)
                pi_dc.access_token = discord_access_token
                meta = dict(pi_dc.platform_metadata) if pi_dc.platform_metadata else {}
                meta["discord_id"] = discord_id
                meta["username"] = discord_username
                pi_dc.platform_metadata = meta
                flag_modified(pi_dc, "platform_metadata")
      
            # 4. Upsert Google PlatformIntegration
            if google_id:
                pi_go = db.query(PlatformIntegrationTable).filter_by(
                    platform_name="google", user_id=user.id
                ).first()
                if not pi_go:
                    pi_go = PlatformIntegrationTable(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        platform_name="google",
                        connected_at=datetime.now(timezone.utc).isoformat()
                    )
                    db.add(pi_go)
                pi_go.access_token = google_access_token
                meta = dict(pi_go.platform_metadata) if pi_go.platform_metadata else {}
                meta["google_id"] = google_id
                meta["name"] = google_name
                meta["picture"] = google_picture
                pi_go.platform_metadata = meta
                flag_modified(pi_go, "platform_metadata")
    
            db.commit()
    
            # Check if fully onboarded
            integrations = db.query(PlatformIntegrationTable).filter_by(user_id=user.id).all()
            platforms_connected = [pi.platform_name for pi in integrations]
            is_fully_onboarded = (
                "github" in platforms_connected or
                "discord" in platforms_connected or
                "google" in platforms_connected 
            )
            return {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "is_new_user": not is_fully_onboarded
            }
        except OperationalError as e:
            db.rollback()
            if "neon:retryable" in str(e) and attempt < retries - 1:
                time.sleep(1)
                continue
            print(f"[USER PROFILE] ❌ OperationalError: {e}")
            raise e
        except Exception as e:
            print(f"[USER PROFILE] ❌ Failed to save user profile: {e}")
            db.rollback()
            raise e
        finally:
            db.close()
            sys.stdout.flush()


def get_frontend_url(request, return_url: Optional[str] = None) -> str:
    allowed_origins = [
        "https://orchestra-frontend-roan.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
        FRONTEND_URL,
    ]

    from urllib.parse import urlparse
    if return_url:
        parsed = urlparse(return_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in allowed_origins:
            return return_url

    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in allowed_origins:
            return origin
            
    return FRONTEND_URL
