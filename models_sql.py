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
    assigned_to = Column(String, nullable=True) # Mapped to username
    project_id = Column(String, nullable=True, index=True)
    platform_integration_id = Column(String, nullable=True) # New FK to platform integrations
    order = Column(Integer, nullable=True)
    created_at = Column(String)

    pr_number = Column(Integer, nullable=True)
    branch = Column(String, nullable=True)

    # Store simple lists as JSON inside PostgreSQL
    depends_on = Column(JSON, default=list)
    history = Column(JSON, default=list)


class UserTable(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, nullable=True)
    created_at = Column(String)
    updated_at = Column(String)

class PlatformIntegrationTable(Base):
    __tablename__ = "platform_integrations"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String) # Foreign key to users.id
    platform_name = Column(String, index=True)
    access_token = Column(String)
    platform_metadata = Column(JSON)
    connected_at = Column(String)
