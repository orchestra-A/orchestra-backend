import uuid
from sqlalchemy import Column, String, Integer, JSON, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
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
    status = Column(String, default="PENDING")
    track = Column(String, nullable=True)
    description = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)
    platform = Column(String, nullable=True)
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
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    created_at = Column(String)
    updated_at = Column(String)
    skills = Column(JSON, default=list)

class PlatformIntegrationTable(Base):
    __tablename__ = "platform_integrations"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String) # Foreign key to users.id
    platform_name = Column(String, index=True)
    access_token = Column(String)
    platform_metadata = Column(JSON)
    connected_at = Column(String)


class ProjectTable(Base):
    __tablename__ = "projects"

    # Unique project identifier
    id = Column(String, primary_key=True, index=True, default=lambda: f"proj_{uuid.uuid4().hex[:8]}")

    # Name of the project (max 255 characters)
    name = Column(String(255), nullable=False, index=True)

    # Optional detailed description of the project
    description = Column(Text, nullable=True)

    # ID of the user who created the project
    created_by = Column(String, nullable=True, index=True)

    # List of technologies used in the project
    tech_stack = Column(JSON, nullable=True)

    # List of user IDs who are members of the project
    members = Column(JSON, nullable=True)

    # ISO 8601 timestamp of when the project was created
    created_at = Column(String, nullable=False)

    # ISO 8601 timestamp of when the project was last updated
    updated_at = Column(String, nullable=False)

