from __future__ import annotations
import sys
import os
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services.discord_service import start_discord_bot
from app.routes import github, discord, auth, websocket, tasks, projects, graph, ai, events

app = FastAPI(
    title="Timeline Orchestra Backend",
    description="Infrastructure layer for Timeline Orchestra",
    version="0.7.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://orchestra-frontend-roan.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    # Runs when FastAPI server starts. Starts the Discord bot as a background task.
    print("[STARTUP] Server starting...")
    sys.stdout.flush()

    # Create tables in the database if they don't exist
    from database import engine, Base
    import models_sql  # registers UserTable, PlatformIntegrationTable, etc.
    Base.metadata.create_all(bind=engine)
    print("[STARTUP] Database tables verified/created.")
    sys.stdout.flush()

    asyncio.create_task(start_discord_bot())
    print("[STARTUP] Discord bot task created")
    sys.stdout.flush()

    from scheduler import start_scheduler

    start_scheduler()
    print("[STARTUP] WebSocket Cron Scheduler started")
    sys.stdout.flush()


@app.on_event("shutdown")
async def shutdown_event():
    from scheduler import stop_scheduler

    stop_scheduler()
    print("[SHUTDOWN] WebSocket Cron Scheduler stopped")
    sys.stdout.flush()


@app.get("/")
async def health_check():
    return "Orchestra Backend Set by Sarvyagya & Arnav"


# Include routes
app.include_router(github.router)
app.include_router(discord.router)
app.include_router(auth.router)
app.include_router(websocket.router)
app.include_router(tasks.router)
app.include_router(projects.router)
app.include_router(graph.router)
app.include_router(ai.router)
app.include_router(events.router)
