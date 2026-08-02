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

## Component Descriptions

### Entry Points
- **`main.py`**: Bootstrap wrapper that imports the FastAPI app from `app.main` and initializes key services.
- **`app/main.py`**: Creates the FastAPI application instance, configures CORS middleware, registers route handlers, and sets up startup/shutdown events.

### Core Configuration (`app/core/`)
- **`config.py`**: Centralized environment variable management. Loads all API keys and configuration from environment variables with sensible defaults.

### Routes (`app/routes/`)
The routing layer handles HTTP request/response lifecycle:

| Route File | Endpoint Pattern | Description |
|------------|------------------|-------------|
| `auth.py` | `/auth/*` | OAuth flows for GitHub, Discord, Google |
| `github.py` | `/webhook/github` | GitHub webhook receiver and processor |
| `discord.py` | `/webhook/discord` | Discord webhook endpoints |
| `tasks.py` | `/tasks/*` | Task CRUD operations with state management |
| `events.py` | `/events` | Event retrieval and filtering |
| `projects.py` | `/projects/*` | Project management, tracking configurations, and cascading deletions |
| `graph.py` | `/graph/*` | Graph database query endpoints |
| `websocket.py` | `/ws` | Real-time WebSocket connections |

### Services (`app/services/`)
Business logic layer that orchestrates operations:

- **`github_service.py`**: Handles GitHub API calls, webhook signature validation, and repository operations.
- **`discord_service.py`**: Manages Discord bot lifecycle, message processing, and channel interactions.
- **`task_service.py`**: Core task business logic including creation, updates, and state transitions.
- **`event_service.py`**: Event persistence and retrieval from PostgreSQL.
- **`oauth_service.py`**: OAuth token exchange and refresh logic for all platforms.
- **`graph_service.py`**: Neo4j graph database synchronization for task relationships.
- **`ai_service.py`**: Proxy layer for AI service interactions (blueprints, graphs) featuring real-time streaming and Neo4j deletion cleanup.
- **`standup_service.py`**: Generates standup reports from event data.

### Schemas (`app/schemas/`)
Pydantic models for request validation and response serialization:

- **`task.py`**: Task creation/update request models, task response schemas.
- **`ai.py`**: AI service request/response models for proxy endpoints.

### Utilities (`app/utils/`)
Shared helper functions:

- **`websocket_manager.py`**: `ConnectionManager` class that handles WebSocket connections, disconnections, and message broadcasting to all connected clients.

### Core Modules (Root Level)

| Module | Purpose |
|--------|---------|
| `models.py` | `NormalizedEvent` Pydantic model - the universal event schema |
| `models_sql.py` | SQLAlchemy ORM models: `EventTable`, `TaskTable`, `UserTable`, `PlatformIntegrationTable`, `ProjectTable` (with dynamic tracking) |
| `database.py` | Database engine creation, session management, connection pooling with retry logic |
| `state_machine.py` | Task state transitions (`PENDING → IN_PROGRESS → COMPLETED → BLOCKED`) with history tracking |
| `scheduler.py` | APScheduler-based background jobs: daily summaries, heartbeats, stale task detection |
| `normalizer.py` | Transforms raw GitHub/Discord/Figma payloads into `NormalizedEvent` objects |

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
- `history` (JSON): State change audit trail

**events**
- `id` (String, PK): UUID event identifier
- `platform` (String): Source platform (github/discord/figma)
- `event_type` (String): Event category (push/pull_request/message)
- `actor` (String): Event triggerer username
- `raw_metadata` (JSON): Original payload preserved

**projects**
- `id` (String, PK): Generated project ID (proj_XXXXXXXX)
- `name` (String): Project name
- `members` (JSON): Team member user IDs
- `tech_stack` (JSON): Technology list
- `tracked_repos` (JSON): Dynamically tracked GitHub repositories
- `tracked_channels` (JSON): Dynamically tracked Discord webhook URLs
- `is_archived` (Boolean): Archive status flag

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

## Current Status

- **Week 1:** Complete (Infrastructure boilerplate & Webhooks).
- **Week 2:** Complete (Data Pipeline Normalizer).
- **Week 3:** Complete (Task REST Endpoints, WebSocket Integration, Background Schedulers).
- **Week 4:** Complete (Full PostgreSQL Migration for tasks, events, user profiles, and dynamic platform integrations).
- **Week 5:** Complete (AI Server Proxy Integration for blueprints and graphs).
- **Week 6:** Complete (Database Seeding, Task Status API with Pydantic schemas, AI proxy refinement, and system stability fixes).
- **Week 7:** Complete (Dynamic project tracking configuration, AI streaming capabilities, cascading deletions, and automated GitHub webhooks).
