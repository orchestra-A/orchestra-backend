"""
test_summarizer.py — Week 5, Member 4
Unit tests for the summarizer — no server, no Discord needed.
Run with: python test_summarizer.py

Tests:
  1. DeveloperDigest builds correctly from events
  2. Headline is human-readable
  3. is_empty() works
  4. TeamDigest groups all developers correctly
  5. Tasks within time window are included
  6. Tasks outside time window are excluded
  7. Discord button custom_id parsing
  8. JSON round-trip for digest output
"""

import os
import sys
import json
import tempfile
from datetime import datetime, timezone, timedelta

# Point summarizer at temp files so we don't touch real data
import summarizer as sm
import discord_sender as ds

_tmp_events = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
_tmp_events.close()
_tmp_tasks  = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
json.dump({}, open(_tmp_tasks.name, "w"))

sm.EVENTS_FILE = _tmp_events.name
sm.TASKS_FILE  = _tmp_tasks.name

PASS = "✅"
FAIL = "❌"
results = []


def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append(condition)
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))


def section(title: str):
    print(f"\n{'─'*52}")
    print(f"  {title}")
    print(f"{'─'*52}")


def write_events(events: list[dict]):
    with open(sm.EVENTS_FILE, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def write_tasks(tasks: dict):
    with open(sm.TASKS_FILE, "w") as f:
        json.dump(tasks, f)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def hours_ago(h: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


# ─────────────────────────────────────────────
# Test 1: Build developer digest from events
# ─────────────────────────────────────────────
section("Test 1: Build Developer Digest from Events")

push_event = {
    "platform": "github", "event_type": "push",
    "actor": "arnav", "timestamp": now_iso(),
    "action_summary": "arnav pushed 3 commit(s) to feature/task-12",
    "raw_metadata": {"branch": "feature/task-12", "commit_count": 3, "commits": []}
}
pr_merged = {
    "platform": "github", "event_type": "pull_request",
    "actor": "arnav", "timestamp": now_iso(),
    "action_summary": "arnav closed PR #42: Fixes task-42",
    "raw_metadata": {"action": "closed", "merged": True, "pr_number": 42, "pr_title": "Fixes task-42"}
}
discord_msg = {
    "platform": "discord", "event_type": "message",
    "actor": "arnav", "timestamp": now_iso(),
    "action_summary": "arnav posted in #dev",
    "raw_metadata": {"content": "done!", "channel_id": "123"}
}

write_events([push_event, pr_merged, discord_msg])
write_tasks({})

period_start = hours_ago(25)
period_end   = now_iso()

digest = sm.build_developer_digest("arnav", sm._load_events(), sm._load_tasks(), period_start, period_end)

check("Actor is arnav", digest.actor == "arnav")
check("1 push recorded", len(digest.pushes) == 1)
check("Total commits is 3", digest.total_commits() == 3)
check("1 PR merged recorded", len(digest.prs_merged) == 1)
check("0 PRs opened", len(digest.prs_opened) == 0)
check("1 Discord message", digest.discord_messages == 1)
print(f"\n  → Headline: {digest.headline()}")


# ─────────────────────────────────────────────
# Test 2: Headline generation
# ─────────────────────────────────────────────
section("Test 2: Headline Generation")

check("Headline is non-empty string", isinstance(digest.headline(), str) and bool(digest.headline()))
check("Headline mentions commits", "commit" in digest.headline().lower() or "pr" in digest.headline().lower())

# Empty digest headline
empty = sm.DeveloperDigest(actor="nobody", period_start=period_start, period_end=period_end)
check("Empty digest headline is 'No activity recorded'", empty.headline() == "No activity recorded")


# ─────────────────────────────────────────────
# Test 3: is_empty() detection
# ─────────────────────────────────────────────
section("Test 3: is_empty() Detection")

check("Active digest is not empty", not digest.is_empty())
check("Fresh digest IS empty", empty.is_empty())

# Digest with only Discord messages — NOT empty
discord_only = sm.DeveloperDigest(actor="user", period_start=period_start, period_end=period_end)
discord_only.discord_messages = 5
check("Discord-only digest is not empty", not discord_only.is_empty())


# ─────────────────────────────────────────────
# Test 4: Task state assignment in digest
# ─────────────────────────────────────────────
section("Test 4: Task States in Digest")

write_tasks({
    "task-12": {
        "id": "task-12", "title": "Build webhook",
        "state": "COMPLETED", "assigned_to": "arnav",
        "updated_at": now_iso(), "history": []
    },
    "task-15": {
        "id": "task-15", "title": "Build normalizer",
        "state": "IN_PROGRESS", "assigned_to": "arnav",
        "updated_at": now_iso(), "history": []
    },
    "task-7": {
        "id": "task-7", "title": "Fix login bug",
        "state": "BLOCKED", "assigned_to": "arnav",
        "updated_at": now_iso(), "history": []
    },
    "task-99": {
        "id": "task-99", "title": "Someone else's task",
        "state": "IN_PROGRESS", "assigned_to": "other_dev",
        "updated_at": now_iso(), "history": []
    },
})

digest2 = sm.build_developer_digest("arnav", sm._load_events(), sm._load_tasks(), period_start, period_end)

check("task-12 appears in tasks_completed", any(t["id"] == "task-12" for t in digest2.tasks_completed))
check("task-15 appears in tasks_in_progress", any(t["id"] == "task-15" for t in digest2.tasks_in_progress))
check("task-7 appears in tasks_blocked", any(t["id"] == "task-7" for t in digest2.tasks_blocked))
check("task-99 (other dev) NOT in digest", not any(t["id"] == "task-99" for t in digest2.tasks_in_progress))
print(f"\n  → Headline: {digest2.headline()}")


# ─────────────────────────────────────────────
# Test 5: TeamDigest groups multiple developers
# ─────────────────────────────────────────────
section("Test 5: TeamDigest Groups All Developers")

write_events([
    {**push_event, "actor": "arnav"},
    {**push_event, "actor": "priya", "raw_metadata": {"branch": "feat/x", "commit_count": 1, "commits": []}},
    {**discord_msg, "actor": "arnav"},
    {**discord_msg, "actor": "rohit"},
])
write_tasks({})

team = sm.build_team_digest(hours=24)

actors_in_team = [d.actor for d in team.developers]
check("arnav in team", "arnav" in actors_in_team)
check("priya in team", "priya" in actors_in_team)
check("rohit in team", "rohit" in actors_in_team)
check("active_developers() excludes empty ones", len(team.active_developers()) <= len(team.developers))
print(f"\n  → {len(team.developers)} developers, {len(team.active_developers())} active")


# ─────────────────────────────────────────────
# Test 6: Time window filtering
# ─────────────────────────────────────────────
section("Test 6: Time Window Filtering")

old_event = {
    "platform": "github", "event_type": "push",
    "actor": "arnav", "timestamp": hours_ago(48),  # 48 hours ago — outside 24h window
    "action_summary": "old push", "raw_metadata": {"branch": "main", "commit_count": 1, "commits": []}
}
recent_event = {
    "platform": "github", "event_type": "push",
    "actor": "arnav", "timestamp": hours_ago(1),   # 1 hour ago — inside window
    "action_summary": "recent push", "raw_metadata": {"branch": "feature/task-1", "commit_count": 2, "commits": []}
}
write_events([old_event, recent_event])

recent_events = sm._load_events(since=hours_ago(24))
check("Recent events loaded (1h ago)", len(recent_events) == 1)
check("Old event (48h ago) excluded", all(e["timestamp"] > hours_ago(25) for e in recent_events))

team2 = sm.build_team_digest(hours=24)
arnav_digest = next((d for d in team2.developers if d.actor == "arnav"), None)
check("Only recent push in 24h digest", arnav_digest is not None and len(arnav_digest.pushes) == 1)
check("Commit count from recent push only", arnav_digest.total_commits() == 2 if arnav_digest else False)


# ─────────────────────────────────────────────
# Test 7: Discord button custom_id parsing
# ─────────────────────────────────────────────
section("Test 7: Discord Button custom_id Parsing")

cases = [
    ("standup_done_arnav",       {"actor": "arnav",      "action": "done",       "new_state": "COMPLETED"}),
    ("standup_inprogress_priya", {"actor": "priya",      "action": "inprogress", "new_state": "IN_PROGRESS"}),
    ("standup_blocked_rohit",    {"actor": "rohit",      "action": "blocked",    "new_state": "BLOCKED"}),
    ("random_garbage",           {}),
    ("",                         {}),
]

for custom_id, expected in cases:
    result = ds.parse_button_interaction(custom_id)
    if expected:
        check(f"'{custom_id}' parses correctly",
              result.get("actor") == expected["actor"] and
              result.get("new_state") == expected["new_state"])
    else:
        check(f"'{custom_id}' returns empty dict for invalid input", result == {})


# ─────────────────────────────────────────────
# Test 8: digest .to_dict() JSON round-trip
# ─────────────────────────────────────────────
section("Test 8: Digest JSON Serialization Round-Trip")

write_events([push_event, pr_merged, discord_msg])
write_tasks({})

digest3 = sm.build_single_developer_digest("arnav", hours=24)
d = digest3.to_dict()

check("to_dict() returns dict", isinstance(d, dict))
check("actor key present", "actor" in d)
check("headline key present", "headline" in d)
check("pushes count present", "pushes" in d)
check("total_commits count present", "total_commits" in d)
check("tasks_completed list present", isinstance(d.get("tasks_completed"), list))
check("discord_messages count present", "discord_messages" in d)

# Serialise to JSON and back
json_str = json.dumps(d)
reloaded = json.loads(json_str)
check("JSON serialization succeeds", bool(json_str))
check("Actor survives round-trip", reloaded.get("actor") == "arnav")


# ─────────────────────────────────────────────
# Test 9: _state_color helper
# ─────────────────────────────────────────────
section("Test 9: Discord Embed Color Logic")

blocked_digest = sm.DeveloperDigest(actor="x", period_start=period_start, period_end=period_end)
blocked_digest.tasks_blocked = [{"id": "task-1", "title": "blocked"}]
check("Blocked digest → red color", ds._state_color(blocked_digest) == 0xED4245)

done_digest = sm.DeveloperDigest(actor="x", period_start=period_start, period_end=period_end)
done_digest.tasks_completed = [{"id": "task-2", "title": "done"}]
check("All-done digest → green color", ds._state_color(done_digest) == 0x57F287)

inprogress_digest = sm.DeveloperDigest(actor="x", period_start=period_start, period_end=period_end)
inprogress_digest.tasks_in_progress = [{"id": "task-3", "title": "wip"}]
check("In-progress digest → yellow color", ds._state_color(inprogress_digest) == 0xFEE75C)


# ─────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────
os.unlink(sm.EVENTS_FILE)
os.unlink(sm.TASKS_FILE)


# ─────────────────────────────────────────────
# Final results
# ─────────────────────────────────────────────
total  = len(results)
passed = sum(results)
failed = total - passed

print(f"\n{'═'*52}")
print(f"  Results: {passed}/{total} tests passed")
if failed:
    print(f"  ⚠️  {failed} test(s) failed — check output above")
else:
    print(f"  🎉 All tests passed — summarizer is solid!")
print(f"{'═'*52}\n")

sys.exit(0 if failed == 0 else 1)
