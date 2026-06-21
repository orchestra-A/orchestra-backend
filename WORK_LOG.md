# Orchestra Project Work Log

This file tracks the work done on the Orchestra Backend project with dates, times, and brief descriptions of the tasks performed.

## 2026-06-16

### 14:30 - 14:33
- **Branch Management**: Pulled the latest upstream updates from the `main` branch on GitHub into the local personal branch `back`. Preserved and resolved a merge conflict on the Discord OAuth login callback's bot invite URL in [main.py](file:///Users/sarvyagyaprakash/DRIVE/CODE/orchestra-backend/main.py).
- **Local Branch Sync**: Pulled `main` branch from GitHub to update the local `main` branch, ensuring it is up to date, then switched back to `back` branch and restored local working changes.

### 14:38 - 15:06
- **Database Migration & Sync Implementation**:
  - Implemented persistent database tables (`connected_users`, `discord_users`, and `user_profiles`) in `models_sql.py` to prevent OAuth session wipes on Render redeploys.
  - Refactored `main.py` ingestion and OAuth flow storage to save and load data from the database.
  - Configured a local SQLite database fallback (`orchestra.db`) for seamless local testing.
  - Added `from __future__ import annotations` and resolved `str | None` type union issues to support older Python 3.9 environments.
  - Implemented `sync_task_status_to_neo4j` helper to update the Neo4j Graph DB status (`PATCH /tasks/{task_id}/status`) upon task state changes.
  - Connected PostgreSQL and State Machine automated status transitions to trigger Neo4j database sync automatically.
  - Created a test verification script and successfully validated the SQL saving and Neo4j API sync.

### 14:45
- **Git Ignore Security**: Added `WORK_LOG.md` to `.gitignore` to prevent the log from being tracked or pushed to GitHub.

## 2026-06-17

### 12:02 - 12:05
- **Neo4j Sync Function Refactor**: Replaced the `sync_task_status_to_neo4j` helper function in [main.py](file:///Users/sarvyagyaprakash/DRIVE/CODE/orchestra-backend/main.py) with the specific requested implementation, adding `GRAPH_API_URL` and `INTERNAL_API_KEY` global configuration parameters using environment variables.

### 12:13
- **Environment Configuration**: Updated the local [.env](file:///Users/sarvyagyaprakash/DRIVE/CODE/orchestra-backend/.env) file to configure `GRAPH_API_URL`, aligning the local environment variables with the Render production configuration.

### 12:35
- **Commit Intel Endpoint**: Added a new `GET /commit-intel` route directly below the `GET /discord/activity` route in [main.py](file:///Users/sarvyagyaprakash/DRIVE/CODE/orchestra-backend/main.py) to correlate Discord activity with actual GitHub events and task mentions (using regex pattern `task-\d+` or `T\d{3}`).

### 15:10 - 15:50
- **Security & Logic Vulnerability Fixes**:
  - **Webhook Signature Enforcement**: Enforced signature verification in `/webhook/github` for registered users and rejected unauthorized senders, preventing spoofed event injection.
  - **Task Data Migration**: Fully migrated task creation (`POST /tasks`) and single task queries (`GET /tasks/{task_id}`) to the database (`TaskTable`) to prevent data loss on Render redeploys and eliminate UI status desyncs.
  - **Daily Standup Database Migration**: Updated the Discord standup bot checking (`get_user_standup_data`) and confirmation (`confirm_standup_tasks`) routines to read/write from `EventTable` and `TaskTable` databases instead of ephemeral local JSON files.
  - **Regex Parsing Fix**: Replaced capturing groups with non-capturing groups `(?:...)` in `extract_task_references` to prevent returning action verb keywords (e.g. `closes`) as malformed task IDs.
  - **Task ID Normalization**: Modified the branch and PR title parsing in `state_machine.py` to extract and normalize task IDs to the standard zero-padded database format `task_00X` (e.g. `task_012` instead of `task-12`), preventing duplicate task creation.
  - **SQLite Timeout**: Added `timeout=30` to connection arguments in `database.py` to allow database query retries and prevent locks during concurrent webhook writes.
  - **Commit Intel Robustness**: Added string coercion checks in `/commit-intel` to prevent crashes when message contents are null.

## 2026-06-21

### 15:07 - 15:15
- **Normalizer Audit and Data Quality Enhancements**:
  - **Timestamp Safety Checks**: Implemented a private helper `_extract_timestamp` in [normalizer.py](file:///Users/sarvyagyaprakash/DRIVE/CODE/orchestra-backend/normalizer.py) to validate the root payload `timestamp` field, safely converting non-dict values (like epoch integers) to string and falling back to current UTC time for missing, empty, or dict values.
  - **Actor Fallback Logic**: Added robust fallback check sequences for all normalizers (GitHub push, PR, issue, release, Discord message, Figma event) in [normalizer.py](file:///Users/sarvyagyaprakash/DRIVE/CODE/orchestra-backend/normalizer.py) to check alternative payload fields (like `sender`, `author`, `triggered_by`, `user`, etc.) and prevent them from defaulting to `"unknown"`.
  - **Render Backend URL Update**: Replaced all occurrences of the old backend Render URL (`https://orchestra-backend-3l80.onrender.com`) with the new Render URL (`https://orchestra-backend-30fy.onrender.com`) across [main.py](file:///Users/sarvyagyaprakash/DRIVE/CODE/orchestra-backend/main.py) (GitHub webhook URL registration, Discord redirect callback URL, Discord callback payload validation, and websocket configuration comment) and [README.md](file:///Users/sarvyagyaprakash/DRIVE/CODE/orchestra-backend/README.md).
  - **Test Suite Updates**: Added new test cases (Test 11 and Test 12) to [test_normalizer.py](file:///Users/sarvyagyaprakash/DRIVE/CODE/orchestra-backend/tests/test_normalizer.py) to verify the new safety logic for timestamp types and actor fallbacks, achieving 63/63 passing tests.

