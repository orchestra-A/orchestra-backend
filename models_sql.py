from sqlalchemy import Column, String, Integer, JSON
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
