import hmac
import hashlib
import sys
import httpx
from app.core.config import GITHUB_WEBHOOK_SECRET_KEY, BACKEND_URL
from app.services.oauth_service import save_unified_user_profile

def generate_user_webhook_secret(github_username: str) -> str:
    # Generates a unique webhook secret per user using HMAC-SHA256.
    combined = f"{GITHUB_WEBHOOK_SECRET_KEY}:{github_username}"
    return hmac.new(
        GITHUB_WEBHOOK_SECRET_KEY.encode(), combined.encode(), hashlib.sha256
    ).hexdigest()[:32]


async def register_github_webhook(
    access_token: str, github_username: str, repo_full_name: str
) -> dict:
    # Auto-registers a webhook on the user's GitHub repo after OAuth login.
    # Generate a unique secret for this user
    webhook_secret = generate_user_webhook_secret(github_username)

    # This is the URL GitHub will send events to
    # Every user's events come to the same endpoint
    # We identify whose event it is from the payload
    webhook_url = f"{BACKEND_URL}/webhook/github"

    # The webhook configuration we send to GitHub
    webhook_config = {
        "name": "web",
        "active": True,
        "events": [
            "push",  # Someone pushed code
            "pull_request",  # PR opened, closed, merged
            "issues",  # Issue created, closed, commented
        ],
        "config": {
            "url": webhook_url,
            "content_type": "json",
            "secret": webhook_secret,
            "insecure_ssl": "0",
        },
    }

    # Call GitHub API to create the webhook
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/repos/{repo_full_name}/hooks",
            json=webhook_config,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    if response.status_code == 201:
        print(f"[GITHUB] ✅ Webhook registered for {repo_full_name}")
        sys.stdout.flush()
        return {
            "success": True,
            "repo": repo_full_name,
            "webhook_id": response.json().get("id"),
            "events": ["push", "pull_request", "issues"],
        }
    elif response.status_code == 422:
        # 422 means webhook already exists on this repo
        print(f"[GITHUB] ℹ️ Webhook already exists for {repo_full_name}")
        sys.stdout.flush()
        return {
            "success": True,
            "repo": repo_full_name,
            "note": "Webhook already registered",
        }
    else:
        print(f"[GITHUB] ❌ Failed to register webhook: {response.status_code}")
        print(f"[GITHUB] Response: {response.text}")
        sys.stdout.flush()
        return {
            "success": False,
            "repo": repo_full_name,
            "error": response.text,
            "status_code": response.status_code,
        }


def save_connected_user(
    github_username: str, access_token: str, repo_full_name: str, webhook_result: dict
) -> None:
    # Saves the connected user's information to the database.
    save_unified_user_profile(
        github_username=github_username,
        github_access_token=access_token,
        github_repo=repo_full_name
    )
