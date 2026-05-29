# Orchestra Central Backend

This repository contains the centralized API server for the Orchestra project, handling live ingestion and data normalization across all supported platforms.

## Architecture Overview

The backend is composed of two primary tracks working in tandem:

### 1. Infrastructure Layer
Responsible for core server hosting, API endpoint routing, and receiving incoming webhook events securely.
- Exposes a FastAPI application to the web using `ngrok`.
- Catches live webhook events via dedicated endpoints (`/webhook/github`, `/webhook/discord`, `/webhook/figma`).
- Validates payload security (e.g., verifying `X-Hub-Signature-256` HMAC hashes for GitHub).
- Serves static task mock data for the frontend team at `/tasks`.

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
```bash
# Start the FastAPI server locally
uvicorn main:app --reload --port 8000

# Expose the local server to the internet using ngrok
ngrok http 8000
```
*(Note: A permanent ngrok URL for live webhooks will be provided by Member 3).*

### 4. Testing Endpoints
- **Receive Webhook (Local Test):**
  ```bash
  curl -X POST http://localhost:8000/webhook/github -H "X-GitHub-Event: push" -d "{}"
  ```
- **View Normalized Events:** Open `http://localhost:8000/events` in your browser.

---

## Current Status

- **Week 1:** Complete (Infrastructure boilerplate).
- **Week 2:** Complete (Semantic Data Normalizer merged with Member 3's infrastructure). Live tests for Day 4 and Day 5 were conducted on a temporary ngrok URL; pending a permanent URL from Member 3 for final Discord and Figma webhooks.
