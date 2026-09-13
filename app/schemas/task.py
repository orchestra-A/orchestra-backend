from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class TaskStatusUpdate(BaseModel):
    status: str

class TaskAssignRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[str] = None
    track: Optional[str] = None
    points: Optional[int] = None

class TaskCreateRequest(BaseModel):
    title: str = "Untitled"
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    id: Optional[str] = None
    track: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    updated_at: Optional[str] = None
    platform: Optional[str] = None
    assigned_to: Optional[str] = None
    deadline: Optional[str] = None
    depends_on: Optional[list] = None
    dependencies: Optional[list] = None

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
    depends_on: List[Any] = []
    created_at: str
    pr_number: Optional[int] = None
    branch: Optional[str] = None
    deadline: Optional[str] = None
    history: List[Dict[str, Any]] = []
    points: Optional[int] = None

class GetTasksResponse(BaseModel):
    total: int
    tasks: List[TaskResponse]
