# Week 5 — Quick Start (15 min)

## What's new in Week 5

Week 5 adds the **standup bot** on top of Week 3's state machine:
- **Summarizer** — builds per-developer activity digests
- **Discord sender** — sends digests to Discord (webhook or bot)
- **Interactive buttons** — "✅ Done / 🔄 In Progress / 🔴 Blocked" in Discord

---

## Step 1: Copy files from Week 3 (required)

```bash
cp ../week3-pipeline/state_machine.py .
cp ../week3-pipeline/broadcaster.py .
cp ../week3-pipeline/normalizer.py .
cp ../week3-pipeline/models.py .
```

---

## Step 2: Install dependencies

```bash
pip install -r requirements.txt
```
Same as Week 3 — no new packages.

---

## Step 3: Run unit tests (no server needed)

```bash
python test_summarizer.py
```
Expected: `🎉 All tests passed`

---

## Step 4: Start the server

```bash
uvicorn main:socket_app --reload --port 8000
```

---

## Step 5: Seed some data + test standup

```bash
# Create tasks
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"id": "task-12", "title": "Build webhook receiver"}'

# Simulate a push (moves task to IN_PROGRESS)
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -H "X-Hub-Signature-256: sha256=dummy" \
  -d '{"ref":"refs/heads/feature/task-12","pusher":{"name":"arnav"},"repository":{"full_name":"team/orchestra"},"commits":[{"id":"abc","message":"start"}]}'

# Preview the standup digest (no Discord needed)
curl http://localhost:8000/standup/preview | python -m json.tool

# See just your digest
curl http://localhost:8000/standup/developer/arnav | python -m json.tool
```

---

## Quick Reference: New Endpoints

| Endpoint | What it does |
|----------|-------------|
| `GET /standup/preview` | Preview digest — no Discord needed |
| `GET /standup/developer/{actor}` | One developer's digest |
| `GET /standup/team` | Full team digest |
| `POST /standup/trigger` | Manually trigger morning standup |
| `POST /standup/evening` | Manually trigger evening summary |
| `POST /discord/button` | Handle button click from Member 3's bot |

---

## Setting Up Discord (Day 3-4)

### Option 1: Webhook URL (no bot needed, do this first)
1. Go to your Discord server → any channel → Edit Channel → Integrations → Webhooks
2. Create a webhook, copy the URL
3. Add to `.env`: `DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...`
4. Run: `curl -X POST http://localhost:8000/standup/trigger`
5. Check Discord — you should see the embed! ✅

### Option 2: Bot with buttons (needs Member 3)
1. Ask Member 3 for: `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID`
2. Add both to `.env`
3. Button interactions will be forwarded to your `/discord/button` endpoint

---

## File Overview

```
week5-standup/
├── main.py              # Server (Week 5 version)
├── summarizer.py        # Builds per-developer digests ← NEW
├── discord_sender.py    # Sends to Discord ← NEW
├── scheduler.py         # Enhanced scheduler ← UPGRADED
├── state_machine.py     # FROM WEEK 3 — copy
├── broadcaster.py       # FROM WEEK 3 — copy
├── normalizer.py        # FROM WEEK 2 — copy
├── models.py            # FROM WEEK 2 — copy
├── test_summarizer.py   # Unit tests ← NEW
├── test_server.py       # Integration tests ← NEW
├── requirements.txt
└── .env
```

---

## Scheduler Jobs in Week 5

| Job | When | What |
|-----|------|------|
| `morning_standup` | 9:00 AM UTC | Per-developer digest to Discord |
| `evening_summary` | 6:00 PM UTC | Team-wide recap to Discord |
| `heartbeat` | Every 30s | Keep WebSocket clients alive |
| `stale_task_check` | Every 60min | Flag stuck tasks |
| `weekly_report` | Monday 8AM | 7-day team summary |

---

## If Something's Wrong

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: state_machine` | Copy from Week 3: `cp ../week3-pipeline/state_machine.py .` |
| Discord embed not sending | Check `DISCORD_WEBHOOK_URL` in `.env` is set |
| Button click not working | Check Member 3 is POSTing to `/discord/button` |
| Summarizer returns empty | Make sure you have events in `events.json` first |

Good luck! 🚀
