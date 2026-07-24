import requests
import time
import sys
from app.core.config import GRAPH_API_URL, INTERNAL_API_KEY

def sync_task_status_to_neo4j(task_id: str, status: str) -> bool:
    # Syncs task status to Neo4j for Clover AI; uses synchronous requests to match state_machine.py's sync call path.
    if not GRAPH_API_URL or not INTERNAL_API_KEY:
        print("[GRAPH SYNC] ⚠️ Missing GRAPH_API_URL or INTERNAL_API_KEY — skipping sync")
        sys.stdout.flush()
        return False

    url = f"{GRAPH_API_URL}/tasks/{task_id}/status"

    max_retries = 3
    base_delay = 1.0  # seconds

    for attempt in range(max_retries + 1):
        try:
            response = requests.patch(
                url,
                json={"status": status},
                headers={"x-api-key": INTERNAL_API_KEY},
                timeout=10
            )

            if response.status_code == 200:
                print(f"[GRAPH SYNC] ✅ Neo4j updated: {task_id} → {status}")
                sys.stdout.flush()
                return True
            elif response.status_code >= 500:
                # Server error, worth retrying
                print(f"[GRAPH SYNC] ⚠️ Neo4j sync failed (HTTP {response.status_code}). "
                      f"Attempt {attempt + 1}/{max_retries + 1}")
            else:
                # Client error (4xx) or unexpected status, don't retry
                print(f"[GRAPH SYNC] ❌ Neo4j sync failed for {task_id}: "
                      f"HTTP {response.status_code} — {response.text}")
                sys.stdout.flush()
                return False

        except requests.exceptions.RequestException as e:
            print(f"[GRAPH SYNC] ⚠️ Network error (Attempt {attempt + 1}/{max_retries + 1}): {e}")

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            print(f"[GRAPH SYNC] ⏳ Retrying in {delay}s...")
            sys.stdout.flush()
            time.sleep(delay)

    print(f"[GRAPH SYNC] ❌ Neo4j sync completely failed after {max_retries + 1} attempts for {task_id}.")
    sys.stdout.flush()
    return False
