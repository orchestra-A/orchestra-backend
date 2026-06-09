# Week 5 — Member 4 — Daily Task Breakdown (Days 29–35)

## Overview

Week 5 for Member 4:
1. **Summarizer** — reads events.json + tasks.json → per-developer activity digest
2. **Discord sender** — sends digests to Discord (webhook first, then bot with buttons)
3. **Enhanced scheduler** — morning standup, evening summary, weekly report

---

## Day 1 (Day 29): Setup + Read Summarizer

**Time**: 2-3 hours
**Goal**: Understand the summarizer, run unit tests

### Tasks
- [ ] Copy files from Week 3:
  ```bash
  cp ../week3-pipeline/state_machine.py .
  cp ../week3-pipeline/broadcaster.py .
  cp ../week3-pipeline/normalizer.py .
  cp ../week3-pipeline/models.py .
  ```
- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Read `summarizer.py` — understand `DeveloperDigest` and `TeamDigest`
- [ ] Read `discord_sender.py` — understand webhook vs bot modes
- [ ] Run unit tests: `python test_summarizer.py`

### Deliverable
- [ ] All unit tests pass: `🎉 All tests passed`
- [ ] Screenshot of passing tests

---

## Day 2 (Day 30): Run Server + Preview Standup

**Time**: 3 hours
**Goal**: Server running, standup digest visible via REST

### Tasks
- [ ] Start server: `uvicorn main:socket_app --reload --port 8000`
- [ ] Seed some events (simulate a working day):
  ```bash
  # Create tasks
  curl -X POST http://localhost:8000/tasks \
    -d '{"id":"task-12","title":"Build webhook"}'
  curl -X POST http://localhost:8000/tasks \
    -d '{"id":"task-15","title":"Build normalizer"}'

  # Push to task branches
  curl -X POST http://localhost:8000/webhook \
    -H "X-GitHub-Event: push" \
    -H "X-Hub-Signature-256: sha256=dummy" \
    -d '{"ref":"refs/heads/feature/task-12","pusher":{"name":"arnav"},"repository":{"full_name":"team/orchestra"},"commits":[{"id":"abc","message":"start task 12"}]}'
  ```
- [ ] Preview standup digest:
  ```bash
  curl http://localhost:8000/standup/preview | python -m json.tool
  ```
- [ ] Check developer digest:
  ```bash
  curl http://localhost:8000/standup/developer/arnav | python -m json.tool
  ```
- [ ] Check team digest:
  ```bash
  curl http://localhost:8000/standup/team | python -m json.tool
  ```

### Deliverable
- [ ] Preview endpoint returns meaningful data
- [ ] Your username shows up in the team digest
- [ ] Headline is readable and accurate

---

## Day 3 (Day 31): Connect Discord Webhook

**Time**: 3-4 hours
**Goal**: First Discord embed appearing in a real Discord channel

### Tasks
- [ ] Create a Discord webhook:
  - Go to any Discord server you have
  - Channel → Edit → Integrations → Webhooks → New Webhook
  - Copy the URL
- [ ] Add to `.env`:
  ```
  DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
  ```
- [ ] Restart server and trigger standup:
  ```bash
  curl -X POST http://localhost:8000/standup/trigger
  ```
- [ ] Check Discord — you should see the embed with digest info
- [ ] Screenshot of Discord embed
- [ ] Try evening summary:
  ```bash
  curl -X POST http://localhost:8000/standup/evening
  ```
- [ ] Screenshot of team summary embed

### Deliverable
- [ ] Discord embed visible in a real channel
- [ ] Morning (per-developer) + evening (team) both work

---

## Day 4 (Day 32): Test Multiple Developers

**Time**: 3 hours
**Goal**: Standup works for multiple developers

### Tasks
- [ ] Seed events for multiple developers:
  ```bash
  # Push as "priya"
  curl -X POST http://localhost:8000/webhook \
    -H "X-GitHub-Event: push" \
    -H "X-Hub-Signature-256: sha256=dummy" \
    -d '{"ref":"refs/heads/feature/task-20","pusher":{"name":"priya"},"repository":{"full_name":"team/orchestra"},"commits":[{"id":"xyz","message":"working"}]}'

  # Discord message as "rohit"
  curl -X POST http://localhost:8000/discord \
    -d '{"id":"1","content":"PR ready for review","channel_id":"123","author":{"username":"rohit"}}'
  ```
- [ ] Preview team digest — should now show arnav, priya, rohit
- [ ] Trigger standup — should send 3 separate Discord embeds (one per person)
- [ ] Screenshot showing multiple embeds
- [ ] Verify empty developers don't get a message

### Deliverable
- [ ] Each active developer gets their own Discord embed
- [ ] Inactive developers (no events) are excluded

---

## Day 5 (Day 33): Discord Buttons (coordinate with Member 3)

**Time**: 3-4 hours + Member 3 coordination
**Goal**: Interactive buttons working in Discord

### Tasks
- [ ] Send Member 3 the coordination message (see COORDINATION.md)
- [ ] While waiting: test button endpoint locally:
  ```bash
  # First make sure task-12 is IN_PROGRESS (assigned to arnav)
  # Then simulate button click:
  curl -X POST http://localhost:8000/discord/button \
    -d '{"custom_id":"standup_done_arnav","actor":"arnav"}'
  ```
- [ ] Verify task-12 moved to COMPLETED:
  ```bash
  curl http://localhost:8000/tasks/task-12
  ```
- [ ] Test "blocked" button:
  ```bash
  # Create a new task in PENDING, push to IN_PROGRESS
  curl -X POST http://localhost:8000/tasks -d '{"id":"task-99","title":"blocked test"}'
  # ... push event to put it IN_PROGRESS ...
  # Then click blocked button:
  curl -X POST http://localhost:8000/discord/button \
    -d '{"custom_id":"standup_blocked_arnav","actor":"arnav"}'
  ```
- [ ] When Member 3 is ready:
  - Give them your `/discord/button` endpoint URL
  - They configure their bot to POST button interactions to your endpoint
  - Test end-to-end: Discord button → your server → task state change → WebSocket broadcast

### Deliverable
- [ ] `/discord/button` endpoint correctly updates task states
- [ ] Invalid custom_ids return 400 (not 500)
- [ ] Coordination message sent to Member 3

---

## Day 6 (Day 34): Scheduler + Stale Tasks

**Time**: 2-3 hours
**Goal**: All 5 scheduler jobs verified

### Tasks
- [ ] Verify heartbeat in server logs (every 30 seconds):
  ```
  [WEBSOCKET] 📡 Broadcasting heartbeat: {"timestamp": "..."}
  ```
- [ ] Manually trigger morning standup:
  ```bash
  curl -X POST http://localhost:8000/standup/trigger
  ```
- [ ] Manually trigger evening summary:
  ```bash
  curl -X POST http://localhost:8000/standup/evening
  ```
- [ ] Create a stale task to test the stale check:
  - Create task, push to IN_PROGRESS
  - Manually set `updated_at` to 25 hours ago in `tasks.json`
  - Wait for stale check job to run (or trigger manually from Python shell)
- [ ] Test `?hours=7` parameter on standup:
  ```bash
  curl http://localhost:8000/standup/team?hours=168  # 7-day view
  ```
- [ ] Verify weekly report message format (check `scheduler.py`)

### Deliverable
- [ ] Heartbeat running in logs
- [ ] Morning + evening manually triggered and working
- [ ] Stale task warning visible in WebSocket or Discord

---

## Day 7 (Day 35): Integration Tests + Polish

**Time**: 3 hours
**Goal**: All tests pass, code pushed, team briefed

### Tasks
- [ ] Run all tests:
  ```bash
  python test_summarizer.py        # Unit tests
  python test_server.py            # Integration tests
  ```
- [ ] Fix any failing tests
- [ ] Clean up code — remove debug prints
- [ ] Push all code to GitHub with clear commit message
- [ ] Send team update:
  - Tell Member 3: "`/discord/button` endpoint ready for integration"
  - Tell Members 5 & 6: "Standup digests broadcast via WebSocket as `standup_digest` event"
  - Tell Member 1: "Digest data available at `GET /standup/team`"

### Deliverable
- [ ] All tests pass
- [ ] Code pushed to GitHub
- [ ] Team knows standup is live

---

## Week 5 Checklist

- [ ] Day 29: Setup + unit tests pass ✅
- [ ] Day 30: Server running + preview digest works ✅
- [ ] Day 31: Discord embed appearing in real channel ✅
- [ ] Day 32: Multi-developer standup working ✅
- [ ] Day 33: Button interaction endpoint working ✅
- [ ] Day 34: All scheduler jobs verified ✅
- [ ] Day 35: All tests pass + code pushed ✅
