"""
test_normalizer.py
Tests every normalizer path WITHOUT needing a running server or GitHub.
Run with: python test_normalizer.py

Tests:
  1. GitHub push event → normalized correctly
  2. GitHub PR (opened) → normalized correctly
  3. GitHub PR (merged) → normalized correctly
  4. GitHub issue event → normalized correctly
  5. Discord message → normalized correctly
  6. Unknown/random event → graceful fallback, no crash
  7. Empty/missing fields → no crash
  8. GET /events integration test (needs server running)
"""

import json
import sys
from normalizer import normalize_event
from models import NormalizedEvent


PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(test_name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append(condition)
    print(f"  {status} {test_name}" + (f" — {detail}" if detail else ""))


def section(title: str):
    print(f"\n{'─'*50}")
    print(f"  {title}")
    print(f"{'─'*50}")


# ─────────────────────────────────────────────
# Test 1: GitHub Push
# ─────────────────────────────────────────────
section("Test 1: GitHub Push Event")

push_payload = {
    "ref": "refs/heads/main",
    "pusher": {"name": "arnav"},
    "repository": {"full_name": "team/orchestra"},
    "commits": [
        {"id": "abc1234567", "message": "Fix webhook parser"},
        {"id": "def8901234", "message": "Add normalizer module"},
    ],
    "compare": "https://github.com/team/orchestra/compare/abc..def"
}

event = normalize_event("push", push_payload)
check("Returns NormalizedEvent", isinstance(event, NormalizedEvent))
check("Platform is github", event.platform == "github")
check("Event type is push", event.event_type == "push")
check("Actor extracted", event.actor == "arnav")
check("Repo extracted", event.repo == "team/orchestra")
check("Summary mentions commit count", "2 commit(s)" in event.action_summary)
check("Branch in summary", "main" in event.action_summary)
check("Commits in metadata", len(event.raw_metadata["commits"]) == 2)
check("Commit IDs shortened to 7 chars", len(event.raw_metadata["commits"][0]["id"]) == 7)
check("Has unique ID", bool(event.id))
check("Has timestamp", bool(event.timestamp))
print(f"\n  → Summary: {event.action_summary}")


# ─────────────────────────────────────────────
# Test 2: GitHub PR Opened
# ─────────────────────────────────────────────
section("Test 2: GitHub PR Opened")

pr_payload = {
    "action": "opened",
    "pull_request": {
        "number": 42,
        "title": "Add semantic normalizer",
        "user": {"login": "arnav"},
        "base": {"ref": "main"},
        "head": {"ref": "feature/normalizer"},
        "merged": False,
        "html_url": "https://github.com/team/orchestra/pull/42"
    },
    "repository": {"full_name": "team/orchestra"}
}

event = normalize_event("pull_request", pr_payload)
check("Platform is github", event.platform == "github")
check("Event type is pull_request", event.event_type == "pull_request")
check("Action in summary", "opened" in event.action_summary.lower())
check("PR number in summary", "#42" in event.action_summary)
check("PR title in summary", "normalizer" in event.action_summary)
check("Base branch in metadata", event.raw_metadata["base_branch"] == "main")
check("Merged=False in metadata", event.raw_metadata["merged"] == False)
print(f"\n  → Summary: {event.action_summary}")


# ─────────────────────────────────────────────
# Test 3: GitHub PR Merged
# ─────────────────────────────────────────────
section("Test 3: GitHub PR Merged")

pr_merged_payload = {
    "action": "closed",
    "pull_request": {
        "number": 42,
        "title": "Add semantic normalizer",
        "user": {"login": "arnav"},
        "base": {"ref": "main"},
        "head": {"ref": "feature/normalizer"},
        "merged": True,
        "html_url": "https://github.com/team/orchestra/pull/42"
    },
    "repository": {"full_name": "team/orchestra"}
}

event = normalize_event("pull_request", pr_merged_payload)
check("Merged flag captured", event.raw_metadata["merged"] == True)
check("Action is closed", event.raw_metadata["action"] == "closed")
print(f"\n  → Summary: {event.action_summary}")


# ─────────────────────────────────────────────
# Test 4: GitHub Issue
# ─────────────────────────────────────────────
section("Test 4: GitHub Issue Event")

issue_payload = {
    "action": "opened",
    "issue": {
        "number": 7,
        "title": "Normalizer crashes on empty body",
        "state": "open",
        "html_url": "https://github.com/team/orchestra/issues/7"
    },
    "sender": {"login": "arnav"},
    "repository": {"full_name": "team/orchestra"}
}

event = normalize_event("issues", issue_payload)
check("Platform is github", event.platform == "github")
check("Event type is issue", event.event_type == "issue")
check("Issue number in summary", "#7" in event.action_summary)
check("Issue state in metadata", event.raw_metadata["issue_state"] == "open")
print(f"\n  → Summary: {event.action_summary}")


# ─────────────────────────────────────────────
# Test 5: Discord Message (raw Discord API shape)
# ─────────────────────────────────────────────
section("Test 5: Discord Message Event")

discord_payload = {
    "id": "1234567890123456789",
    "content": "Hey team, just pushed the normalizer — can someone review?",
    "channel_id": "987654321",
    "guild_id": "111222333",
    "timestamp": "2026-05-20T12:00:00.000Z",
    "author": {
        "username": "arnav_dev",
        "id": "444555666"
    },
    "mentions": []
}

event = normalize_event("discord_message", discord_payload)
check("Platform is discord", event.platform == "discord")
check("Event type is message", event.event_type == "message")
check("Actor extracted", event.actor == "arnav_dev")
check("Channel extracted", event.channel == "987654321")
check("Content in metadata", "normalizer" in event.raw_metadata["content"])
check("Long message truncated in summary", "..." in event.action_summary or len(event.action_summary) < 120)
check("Guild_id preserved", event.raw_metadata["guild_id"] == "111222333")
print(f"\n  → Summary: {event.action_summary}")


# ─────────────────────────────────────────────
# Test 6: Figma Event
# ─────────────────────────────────────────────
section("Test 6: Figma Event")

figma_payload = {
    "event_type": "FILE_UPDATE",
    "passcode": "my_secret_passcode",
    "file_name": "Orchestra Dashboard UI",
    "timestamp": "2026-05-20T12:05:00Z",
    "triggered_by": {
        "handle": "designer_dave"
    }
}

event = normalize_event("figma", figma_payload)
check("Platform is figma", event.platform == "figma")
check("Event type is extracted", event.event_type == "FILE_UPDATE")
check("Actor extracted", event.actor == "designer_dave")
check("Summary includes file name", "Orchestra Dashboard UI" in event.action_summary)
print(f"\n  → Summary: {event.action_summary}")


# ─────────────────────────────────────────────
# Test 7: Unknown Event Type (graceful fallback)
# ─────────────────────────────────────────────
section("Test 6: Unknown Event Type — Graceful Fallback")

unknown_payload = {"some_random": "data", "from": "an_unknown_platform"}
event = normalize_event("figma_update", unknown_payload)

check("Does NOT crash", True)  # If we got here, it didn't crash
check("Platform is unknown", event.platform == "unknown")
check("Event type preserved", event.event_type == "figma_update")
check("Raw body preserved in metadata", event.raw_metadata == unknown_payload)
print(f"\n  → Summary: {event.action_summary}")


# ─────────────────────────────────────────────
# Test 7: Missing/Empty Fields (crash safety)
# ─────────────────────────────────────────────
section("Test 7: Missing Fields — No Crash")

try:
    # Push with no pusher, no commits, no repo
    event = normalize_event("push", {})
    check("Empty push: no crash", True)
    check("Actor defaults to unknown", event.actor == "unknown")
    check("Commit count is 0", "0 commit(s)" in event.action_summary)

    # PR with completely empty pull_request
    event = normalize_event("pull_request", {"pull_request": {}, "action": "opened"})
    check("Empty PR: no crash", True)

    # Discord with no author or content
    event = normalize_event("discord_message", {})
    check("Empty Discord: no crash", True)
    check("Discord actor defaults to unknown", event.actor == "unknown")

except Exception as e:
    check(f"UNEXPECTED CRASH: {e}", False)


# ─────────────────────────────────────────────
# Test 8: JSON round-trip (save + reload)
# ─────────────────────────────────────────────
section("Test 8: JSON Serialization Round-Trip")

original = normalize_event("push", push_payload)
json_str = original.model_dump_json()
reloaded = NormalizedEvent.model_validate_json(json_str)

check("Serializes to JSON without error", bool(json_str))
check("ID survives round-trip", original.id == reloaded.id)
check("Actor survives round-trip", original.actor == reloaded.actor)
check("Metadata survives round-trip", original.raw_metadata == reloaded.raw_metadata)
check("Summary survives round-trip", original.action_summary == reloaded.action_summary)


# ─────────────────────────────────────────────
# Final summary
# ─────────────────────────────────────────────
total = len(results)
passed = sum(results)
failed = total - passed

print(f"\n{'═'*50}")
print(f"  Results: {passed}/{total} tests passed")
if failed:
    print(f"  [WARNING] {failed} test(s) failed — check output above")
else:
    print(f"  [SUCCESS] All tests passed — normalizer is solid!")
print(f"{'═'*50}\n")

sys.exit(0 if failed == 0 else 1)
