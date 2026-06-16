from sqlalchemy import Column, String, Integer, JSON, Boolean
from database import Base


class EventTable(Base):
    __tablename__ = "events"
    id = Column(String, primary_key=True, index=True)
    platform = Column(String, index=True)
    event_type = Column(String, index=True)
    actor = Column(String)
    timestamp = Column(String)
    repo = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    action_summary = Column(String)
    raw_metadata = Column(JSON)


class TaskTable(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True, index=True)
    title = Column(String)
    state = Column(String, default="PENDING")
    assigned_to = Column(String, nullable=True)
    project_id = Column(String, nullable=True, index=True)
    order = Column(Integer, nullable=True)
    created_at = Column(String)

    pr_number = Column(Integer, nullable=True)
    branch = Column(String, nullable=True)

    # Store simple lists as JSON inside PostgreSQL
    depends_on = Column(JSON, default=list)
    history = Column(JSON, default=list)


class ConnectedUserTable(Base):
    __tablename__ = "connected_users"
    github_username = Column(String, primary_key=True, index=True)
    repo = Column(String)
    connected_at = Column(String)
    webhook_registered = Column(Boolean)
    webhook_id = Column(Integer, nullable=True)
    access_token = Column(String)


class DiscordUserTable(Base):
    __tablename__ = "discord_users"
    discord_id = Column(String, primary_key=True, index=True)
    discord_username = Column(String)
    access_token = Column(String)
    email = Column(String, nullable=True)
    connected_at = Column(String)


class UserProfileTable(Base):
    __tablename__ = "user_profiles"
    user_id = Column(String, primary_key=True, index=True)
    email = Column(String, nullable=True)
    github_username = Column(String, nullable=True)
    github_access_token = Column(String, nullable=True)
    discord_id = Column(String, nullable=True)
    discord_username = Column(String, nullable=True)
    discord_access_token = Column(String, nullable=True)
    created_at = Column(String)
    updated_at = Column(String)
