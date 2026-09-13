from typing import Optional
from pydantic import BaseModel

class TaskStatusUpdate(BaseModel):
    status: str

class TaskAssignRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[str] = None
    track: Optional[str] = None
    points: Optional[int] = None

class TaskResponse(BaseModel):
    id: str
    title: str
    status: str
    track: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    updated_at: Optional[str] = None
    platform: Optional[str] = None
    assigned_to: Optional[str] = None
    project_id: Optional[str] = None
    order: Optional[int] = None
    depends_on: list = []
    created_at: str
    pr_number: Optional[int] = None
    branch: Optional[str] = None
    deadline: Optional[str] = None
    history: list = []
    points: Optional[int] = None

class GetTasksResponse(BaseModel):
    total: int
    tasks: list[TaskResponse]
