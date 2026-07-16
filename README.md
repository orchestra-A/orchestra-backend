# Orchestra Central Backend

This repository contains the centralized API server for the Orchestra project, handling live ingestion and data normalization across all supported platforms.

## Architecture Overview

The backend is composed of two primary tracks working in tandem:

### 1. Infrastructure Layer
Responsible for core server hosting, API endpoint routing, securely managing user identities, and receiving incoming webhook events.
- Hosted permanently on Render (`https://orchestra-backend-30fy.onrender.com`).
- Manages user profiles and platform integrations securely via a robust PostgreSQL relational database, strictly adhering to the AI Team's Data Contracts.
- Automatically registers GitHub webhooks for new users using OAuth.
- Catches live webhook events via dedicated endpoints (`/webhook/github`, `/webhook/discord`, `/webhook/figma`).
- Validates payload security (e.g., verifying `X-Hub-Signature-256` HMAC hashes for GitHub).
- Serves live task data and REST endpoints (`/tasks`, `/tasks/{id}`) for the frontend team directly from PostgreSQL.
- Hosts a live WebSocket server at `/ws` for real-time state machine updates.

### 2. Data Pipeline Layer
Responsible for transforming raw, multi-platform events into a clean, uniform format.
- Parses incoming JSON payloads and extracts crucial metadata (branch, commits, sender).
- Routes messy data through the **Semantic Data Normalizer** (`normalizer.py`).
  - Persists standardized timeline blocks into a live serverless PostgreSQL database via SQLAlchemy, accessible via the `GET /events` endpoint.

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
DATABASE_URL=postgresql://user:password@endpoint/dbname
BACKEND_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
GITHUB_WEBHOOK_SECRET_KEY=your_secret_here
GITHUB_CLIENT_ID=your_client_id
GITHUB_CLIENT_SECRET=your_client_secret
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_BOT_TOKEN=your_discord_bot_token
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GRAPH_API_URL=https://orchestra-ai-36zm.onrender.com
INTERNAL_API_KEY=your_internal_api_key
```

### 3. Running the Server
The production backend is fully managed and deployed automatically via Render. To run the server locally for development:
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
  curl -X GET http://localhost:8000/tasks?project_id=your_project_id
  ```

---

## Current Status

- **Week 1:** Complete (Infrastructure boilerplate & Webhooks).
- **Week 2:** Complete (Data Pipeline Normalizer).
- **Week 3:** Complete (Task REST Endpoints, WebSocket Integration, Background Schedulers).
- **Week 4:** Complete (Full PostgreSQL Migration for tasks, events, user profiles, and dynamic platform integrations).
- **Week 5:** Complete (AI Server Proxy Integration for blueprints and graphs).
- **Week 6:** Complete (Database Seeding, Task Status API with Pydantic schemas, AI proxy refinement, and system stability fixes).
