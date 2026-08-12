# Orchestra Backend

The centralized API server for the Orchestra project, handling live ingestion, data normalization, database persistence, and real-time state machine updates via WebSockets.

## What it does

1. **Event Ingestion** — catches live webhooks from GitHub, Discord, and Figma
2. **Data Normalization** — scrubs raw, multi-platform payloads into a unified `NormalizedEvent` structure
3. **Live Sync** — broadcasts task state transitions and daily summaries in real-time to all connected frontend clients via WebSockets
4. **AI Proxying** — securely routes requests to the AI server without exposing the `INTERNAL_API_KEY` to the client browser
5. **Persistence** — manages users, tasks, events, and dynamic platform integrations securely in a PostgreSQL relational database

## Project Structure

```
orchestra-backend/
├── app/                          # Main application package
│   ├── __init__.py              # Package initialization
│   ├── main.py                  # FastAPI app creation and middleware setup
│   ├── core/                    # Core configuration and utilities
│   │   ├── __init__.py
│   │   └── config.py            # Environment variables and configuration
│   ├── routes/                  # API route handlers (controllers)
│   │   ├── __init__.py
│   │   ├── auth.py              # OAuth authentication endpoints
│   │   ├── discord.py           # Discord webhook endpoints
│   │   ├── events.py            # Event retrieval endpoints
│   │   ├── github.py            # GitHub webhook endpoints
│   │   ├── graph.py             # Graph database endpoints
│   │   ├── projects.py          # Project CRUD endpoints
│   │   ├── tasks.py             # Task CRUD endpoints
│   │   └── websocket.py         # WebSocket connection handlers
│   ├── schemas/                 # Pydantic models for data validation
│   │   ├── __init__.py
│   │   ├── ai.py                # AI-related request/response schemas
│   │   └── task.py              # Task-related request/response schemas
│   ├── services/                # Business logic and external integrations
│   │   ├── __init__.py
│   │   ├── ai_service.py        # AI service proxy functions
│   │   ├── discord_service.py   # Discord bot and webhook processing
│   │   ├── event_service.py     # Event storage and retrieval
│   │   ├── github_service.py    # GitHub API interactions
│   │   ├── graph_service.py     # Neo4j graph database operations
│   │   ├── oauth_service.py     # OAuth token management
│   │   ├── standup_service.py   # Standup report generation
│   │   └── task_service.py      # Task business logic
│   └── utils/                   # Shared utility functions
│       ├── __init__.py
│       └── websocket_manager.py # WebSocket connection management
├── models.py                    # Normalized event Pydantic model
├── models_sql.py                # SQLAlchemy ORM models for database
├── database.py                  # Database connection and session management
├── state_machine.py             # Task state transition logic
├── scheduler.py                 # Background cron job scheduler
├── normalizer.py                # Semantic data normalizer
├── main.py                      # Application entry point
├── requirements.txt             # Python dependencies
├── Procfile                     # Heroku/Render process definitions
├── .env.example                 # Environment variable template
└── tests/                       # Test files
    └── ...
```

---

## Data Flow

### Webhook Ingestion Flow
```
GitHub/Discord/Figma Webhook
        ↓
   Route Handler (routes/github.py, routes/discord.py)
        ↓
   Signature Validation (services/github_service.py)
        ↓
   Normalizer (normalizer.py)
        ↓
   NormalizedEvent Object
        ↓
   Event Service (services/event_service.py)
        ↓
   PostgreSQL (models_sql.py → EventTable)
        ↓
   State Machine (state_machine.py) [for task-related events]
        ↓
   WebSocket Broadcast (utils/websocket_manager.py)
        ↓
   Connected Frontend Clients
```

### Task Management Flow
```
Task Request (REST API or WebSocket)
        ↓
   Task Service (services/task_service.py)
        ↓
   State Machine Validation (state_machine.py)
        ↓
   PostgreSQL Update (models_sql.py → TaskTable)
        ↓
   Graph DB Sync (services/graph_service.py → Neo4j)
        ↓
   WebSocket Broadcast
        ↓
   Real-time UI Updates
```

---

## Database Schema

### Core Tables

**users**
- `id` (String, PK): Unique user identifier
- `username` (String, unique): Platform username
- `name`, `email` (String): Profile information
- `skills` (JSON): User capabilities array
- `created_at`, `updated_at` (String): ISO timestamps

**tasks**
- `id` (String, PK): Task identifier (e.g., "task_001")
- `title` (String): Task description
- `status` (String): Current state (PENDING/IN_PROGRESS/COMPLETED/BLOCKED)
- `assigned_to` (String): Assigned developer username
- `project_id` (String, FK): Parent project
- `depends_on` (JSON): Dependent task IDs
- `deadline` (String): ISO timestamp for task completion
- `history` (JSON): State change audit trail

**events**
- `id` (String, PK): UUID event identifier
- `platform` (String): Source platform (github/discord/figma)
- `event_type` (String): Event category (push/pull_request/message)
- `actor` (String): Event triggerer username
- `raw_metadata` (JSON): Original payload preserved
- `project_id` (String, FK): Associated project ID

**projects**
- `id` (String, PK): Generated project ID (proj_XXXXXXXX)
- `name` (String): Project name
- `created_by` (String): Creator's user ID
- `members` (JSON): Team member user IDs
- `tech_stack` (JSON): Technology list
- `tracked_repos` (JSON): Dynamically tracked GitHub repositories
- `tracked_channels` (JSON): Dynamically tracked Discord webhook URLs
- `is_archived` (Boolean): Archive status flag
- `blueprint_summary` (String): AI-generated project summary
- `github_repo_url` (String): Primary GitHub repository URL

**platform_integrations**
- `id` (String, PK): Integration identifier
- `user_id` (String, FK): Associated user
- `platform_name` (String): Service name
- `access_token` (String): Encrypted OAuth token

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

## State Machine

The task state machine enforces valid workflow transitions:

```
                    ┌─────────────┐
                    │   BLOCKED   │
                    └──────┬──────┘
                           │
        ┌──────────────────┼──────────────────┐
        ↓                  ↓                  ↓
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│    PENDING    │→ │  IN_PROGRESS  │→ │   COMPLETED   │
└───────────────┘  └───────────────┘  └───────────────┘
```

**Valid Transitions:**
| From | To | Trigger |
|------|----|---------|
| PENDING | IN_PROGRESS | Branch push with task ID |
| PENDING | BLOCKED | Manual or dependency issue |
| IN_PROGRESS | COMPLETED | PR merged |
| IN_PROGRESS | BLOCKED | PR closed without merge |
| IN_PROGRESS | PENDING | Reset/rollback |
| BLOCKED | PENDING | Issue resolved |
| BLOCKED | IN_PROGRESS | Retry started |

---

## Background Jobs

The scheduler runs three recurring tasks:

1. **Daily Summary** (9:00 AM UTC)
   - Aggregates last 24 hours of events
   - Groups activity by developer
   - Broadcasts digest to connected clients

2. **Heartbeat** (Every 30 seconds)
   - Maintains WebSocket connections
   - Detects stale client connections

3. **Stale Task Check** (Every 60 minutes)
   - Identifies tasks stuck in IN_PROGRESS > 24 hours
   - Broadcasts warnings for blocked work

---

## Live URLs

| Service | URL |
|---------|-----|
| AI Server | https://orchestra-ai-36zm.onrender.com |
| Backend | https://orchestra-backend-30fy.onrender.com |

## Stack

Python · FastAPI · PostgreSQL · SQLAlchemy · APScheduler · WebSockets · Render
