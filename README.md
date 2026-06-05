# Orchestra Central Backend

This repository contains the centralized API server for the Orchestra project, handling live ingestion and data normalization across all supported platforms.

## Architecture Overview

The backend is composed of two primary tracks working in tandem:

### 1. Infrastructure Layer
Responsible for core server hosting, API endpoint routing, and receiving incoming webhook events securely.
- Hosted permanently on Render (`https://orchestra-backend-2v5a.onrender.com`).
- Automatically registers GitHub webhooks for new users using OAuth.
- Catches live webhook events via dedicated endpoints (`/webhook/github`, `/webhook/discord`, `/webhook/figma`).
- Validates payload security (e.g., verifying `X-Hub-Signature-256` HMAC hashes for GitHub).
- Serves task mock data and REST endpoints (`/tasks`, `/tasks/{id}`) for the frontend team.
- Hosts a live WebSocket server at `/ws` for real-time state machine updates.

### 2. Data Pipeline Layer
Responsible for transforming raw, multi-platform events into a clean, uniform format.
- Parses incoming JSON payloads and extracts crucial metadata (branch, commits, sender).
- Routes messy data through the **Semantic Data Normalizer** (`normalizer.py`).
- Appends standardized timeline blocks into local JSON storage (`events.json`), accessible via the `GET /events` endpoint.

---

## Getting Started

### 1. Installation
```bash
# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Setup
Create a `.env` file in the root directory and add the following keys:
```
GITHUB_WEBHOOK_SECRET=your_secret_here
# DISCORD_TOKEN and FIGMA_WEBHOOK_SECRET to be added when available
```

### 3. Running the Server
The production backend is fully managed and deployed automatically via Render. However, to run the server locally for development:
```bash
# Start the FastAPI server locally
uvicorn main:app --reload --port 8000
```
*(Note: Webhooks will still route to the live Render server unless you manually configure GitHub to point to a local tunnel like ngrok).*

### 4. Testing Endpoints
- **Receive Webhook (Local Test):**
  ```bash
  curl -X POST http://localhost:8000/webhook/github -H "X-GitHub-Event: push" -d "{}"
  ```
- **Test Task Endpoints:**
  ```bash
  curl -X GET http://localhost:8000/tasks
  curl -X GET http://localhost:8000/tasks/live
  ```
- **View Normalized Events:** Open `http://localhost:8000/events` in your browser.

---

## Current Status

- **Week 1:** Complete (Infrastructure boilerplate & Webhooks).
- **Week 2:** Complete (Data Pipeline Normalizer).
- **Week 3:** In Progress (Task REST Endpoints & WebSocket Integration).
