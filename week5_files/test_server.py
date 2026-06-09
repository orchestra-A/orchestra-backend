"""
test_server.py — Week 5 Integration Tests
Tests the live server for standup/digest/button endpoints.
Run with: python test_server.py  (server must be running)

Start server: uvicorn main:socket_app --reload --port 8000
"""

import urllib.request
import urllib.error
import hmac
import hashlib
import json

BASE   = "http://127.0.0.1:8000"
SECRET = "testsecret123"
PASS = "✅"
FAIL = "❌"


def sign(payload_bytes: bytes) -> str:
    mac = hmac.new(SECRET.encode(), payload_bytes, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def post(path: str, body: dict, extra_headers: dict = None) -> tuple:
    payload = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(BASE + path, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except urllib.error.URLError as e:
        return None, {"error": str(e.reason)}


def get(path: str) -> tuple:
    req = urllib.request.Request(BASE + path)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def patch(path: str, body: dict) -> tuple:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=payload,
                                  headers={"Content-Type": "application/json"}, method="PATCH")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))
    return condition


# ─────────────────────────────────────────────
# Server check
# ─────────────────────────────────────────────
print("\n🔌 Checking server health...")
status, data = get("/health")
if status is None:
    print("  ❌ Server not running. Start it:")
    print("  uvicorn main:socket_app --reload --port 8000")
    exit(1)
print(f"  ✅ Server alive — Week {data.get('week', '')}")
check("Week 5 server", data.get("week") == 5)
check("Discord webhook config shown", "discord_webhook_set" in data)


# ─────────────────────────────────────────────
# Reset
# ─────────────────────────────────────────────
try:
    urllib.request.urlopen(urllib.request.Request(BASE + "/tasks/reset", method="DELETE"))
    urllib.request.urlopen(urllib.request.Request(BASE + "/events/reset", method="DELETE"))
except Exception:
    pass


# ─────────────────────────────────────────────
# Seed data
# ─────────────────────────────────────────────
print("\n── Seeding data ──")
post("/tasks", {"id": "task-12", "title": "Build webhook receiver"})
post("/tasks", {"id": "task-15", "title": "Build normalizer"})

# Push to task-12 branch → IN_PROGRESS
push_payload = {
    "ref": "refs/heads/feature/task-12",
    "pusher": {"name": "arnav"},
    "repository": {"full_name": "team/orchestra"},
    "commits": [{"id": "abc1234567", "message": "Working on task-12"}],
}
pb = json.dumps(push_payload).encode()
post("/webhook", push_payload, {"X-Hub-Signature-256": sign(pb), "X-GitHub-Event": "push"})

# PR merge → task-15 COMPLETED
pr_payload = {
    "action": "closed",
    "pull_request": {
        "number": 15, "title": "Fixes task-15: Build normalizer",
        "user": {"login": "arnav"},
        "base": {"ref": "main"}, "head": {"ref": "feature/task-15"},
        "merged": True, "html_url": "https://github.com/team/orchestra/pull/15"
    },
    "repository": {"full_name": "team/orchestra"},
}
# First put it IN_PROGRESS
push2 = {
    "ref": "refs/heads/feature/task-15",
    "pusher": {"name": "arnav"}, "repository": {"full_name": "team/orchestra"},
    "commits": [{"id": "def456", "message": "normalizer"}]
}
pb2 = json.dumps(push2).encode()
post("/webhook", push2, {"X-Hub-Signature-256": sign(pb2), "X-GitHub-Event": "push"})

pb3 = json.dumps(pr_payload).encode()
post("/webhook", pr_payload, {"X-Hub-Signature-256": sign(pb3), "X-GitHub-Event": "pull_request"})

# Discord message
post("/discord", {"id": "m1", "content": "done!", "channel_id": "123", "author": {"username": "arnav"}})

print("  Seeding complete.")


# ─────────────────────────────────────────────
# Test 1: GET /standup/preview
# ─────────────────────────────────────────────
print("\n── Test 1: GET /standup/preview ──")
status, data = get("/standup/preview")
check("Returns 200", status == 200)
if data:
    check("preview flag is True", data.get("preview") is True)
    check("digest key present", "digest" in data)
    digest = data.get("digest", {})
    check("digest has developers list", isinstance(digest.get("developers"), list))
    check("digest has date", "date" in digest)


# ─────────────────────────────────────────────
# Test 2: GET /standup/developer/arnav
# ─────────────────────────────────────────────
print("\n── Test 2: GET /standup/developer/arnav ──")
status, data = get("/standup/developer/arnav")
check("Returns 200", status == 200)
if data:
    check("Actor is arnav", data.get("actor") == "arnav")
    check("headline present", "headline" in data)
    check("pushes count present", "pushes" in data)
    check("Not empty (has activity)", not (data.get("pushes") == 0 and data.get("discord_messages") == 0))
    print(f"\n  → Headline: {data.get('headline')}")


# ─────────────────────────────────────────────
# Test 3: GET /standup/team
# ─────────────────────────────────────────────
print("\n── Test 3: GET /standup/team ──")
status, data = get("/standup/team")
check("Returns 200", status == 200)
if data:
    check("Has developers list", isinstance(data.get("developers"), list))
    check("Has date", "date" in data)
    check("Has total_commits", "total_commits" in data)
    actors = [d.get("actor") for d in data.get("developers", [])]
    check("arnav in team digest", "arnav" in actors)


# ─────────────────────────────────────────────
# Test 4: POST /standup/trigger (without Discord configured)
# ─────────────────────────────────────────────
print("\n── Test 4: POST /standup/trigger ──")
status, data = post("/standup/trigger", {})
check("Returns 200 (standup triggered)", status == 200)
if data:
    check("Status is 'standup triggered'", data.get("status") == "standup triggered")


# ─────────────────────────────────────────────
# Test 5: Discord button interaction
# ─────────────────────────────────────────────
print("\n── Test 5: POST /discord/button — arnav clicks 'Done' ──")
# task-12 is currently IN_PROGRESS assigned to arnav
status, data = post(
    "/discord/button",
    {"custom_id": "standup_done_arnav", "actor": "arnav"},
)
check("Returns 200", status == 200)
if data:
    check("Actor is arnav", data.get("actor") == "arnav")
    check("new_state is COMPLETED", data.get("new_state") == "COMPLETED")
    check("updated_tasks list present", isinstance(data.get("updated_tasks"), list))
    print(f"\n  → Updated tasks: {data.get('updated_tasks')}")


# ─────────────────────────────────────────────
# Test 6: Discord button — invalid custom_id
# ─────────────────────────────────────────────
print("\n── Test 6: Invalid Button custom_id → 400 ──")
status, data = post("/discord/button", {"custom_id": "garbage_data_xyz"})
check("Returns 400 for invalid custom_id", status == 400)


# ─────────────────────────────────────────────
# Test 7: Unknown developer digest returns empty
# ─────────────────────────────────────────────
print("\n── Test 7: Unknown Developer Digest ──")
status, data = get("/standup/developer/nobody_exists_xyz")
check("Returns 200 (not 404)", status == 200)
if data:
    check("Actor matches", data.get("actor") == "nobody_exists_xyz")
    check("Pushes is 0", data.get("pushes") == 0)
    check("Headline is 'No activity recorded'", "No activity" in data.get("headline", ""))


# ─────────────────────────────────────────────
# Test 8: Hours filter
# ─────────────────────────────────────────────
print("\n── Test 8: hours=1 filter (last 1 hour) ──")
status, data = get("/standup/developer/arnavhours=1")
check("Returns 200 with hours param", status == 200)
# Recent events should still show (seeded just now)
if data:
    check("Activity found in last 1 hour", not (data.get("pushes") == 0 and data.get("discord_messages") == 0))


print("\n✅ Integration tests done.\n")
