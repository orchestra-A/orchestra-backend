# Week 5 — Coordination Messages

## For Member 3 (Infrastructure) — Send on Day 5

```
Hey [Member 3],

The standup bot is almost ready. For the interactive buttons to work,
I need your help on one thing:

Your Discord bot needs to forward button click interactions to my server.

Here's how it works:
1. My server sends a message to Discord with 3 buttons:
   - "✅ All done"         → custom_id: "standup_done_{username}"
   - "🔄 Still in progress" → custom_id: "standup_inprogress_{username}"
   - "🔴 I'm blocked"     → custom_id: "standup_blocked_{username}"

2. When a user clicks a button, your Discord bot receives the interaction.

3. Your bot then forwards it to my endpoint:
   POST http://localhost:8000/discord/button
   { "custom_id": "standup_done_arnav", "actor": "arnav" }

4. My server updates the task state and broadcasts via WebSocket.

Can you:
a) Give me the DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID for my .env?
b) Add the interaction handler to your bot that POSTs to my /discord/button?

I can test my end independently with curl — I just need you to wire up the
Discord interaction forwarding on your side.

Let me know when ready!
```

---

## For Member 1 (Agent Architect) — Send on Day 3

```
Hey [Member 1],

Quick update: the standup digests are live.

You can pull team activity data from:
  GET http://localhost:8000/standup/team         → last 24h
  GET http://localhost:8000/standup/team?hours=168 → last 7 days

Response includes per-developer breakdown:
  - pushes, commits, PRs opened/merged
  - tasks_completed, tasks_in_progress, tasks_blocked
  - discord_messages

Could be useful for your AI skill-mapper — this data shows who's
actively working on what, which correlates to their skills.

Let me know if you need it in a different format!
```

---

## For Member 2 (Knowledge Graph) — Send on Day 4

```
Hey [Member 2],

The standup system now produces structured activity digests.
This data might be valuable for your graph injection.

Available at: GET http://localhost:8000/standup/team

The digest shows:
  - Which developer completed which tasks (tasks_completed list)
  - Current active tasks per developer (tasks_in_progress)
  - Blocked items (tasks_blocked)

This maps nicely to graph edges:
  Developer --[COMPLETED]--> Task
  Developer --[WORKING_ON]--> Task

Should I add a dedicated endpoint that formats this as graph-ready nodes/edges?
```

---

## For Members 5 & 6 (Frontend) — Send on Day 5

```
Hey [Member 5/6],

The standup bot is live. When it runs:
1. It broadcasts a "standup_digest" WebSocket event
2. Each developer's activity shows up in the event stream

Payload for "standup_digest" event:
  {
    "event_type": "standup_digest",
    "actor": "arnav",
    "action_summary": "📊 Standup digest for arnav: ✅ 2 tasks completed · 🔄 1 in progress",
    "raw_metadata": {
      "pushes": 3,
      "total_commits": 7,
      "prs_merged": 1,
      "tasks_completed": ["task-12", "task-15"],
      "tasks_in_progress": ["task-7"],
      "tasks_blocked": []
    }
  }

You can use this to show a "standup feed" in the dashboard.
Also: GET /standup/preview gives the full digest as JSON if you need it.
```

---

## Things You Don't Need to Ask About

### ❌ OAuth/Auth for Discord API
Member 3 handles all authentication. You just need the webhook URL and bot token from them.

### ❌ Discord slash commands
That's Member 3's responsibility. You handle the data logic.

### ❌ Database persistence
Still file-backed in Week 5. Database migration is post-Week 5.

### ❌ AI-generated summaries
The summaries are algorithmic (count-based) for now. AI enhancement is future work.

---

## Quick Reference: What You Own in Week 5

| Responsibility | You (M4) | Member 3 |
|---------------|----------|----------|
| Build digest data | ✅ | — |
| Format Discord embeds | ✅ | — |
| Button custom_id format | ✅ | — |
| Handle /discord/button | ✅ | — |
| Discord bot setup | — | ✅ |
| Bot token | — | ✅ (shares with you) |
| Receive Discord interactions | — | ✅ (forwards to you) |
| Discord slash commands | — | ✅ |

Good luck! 🚀
