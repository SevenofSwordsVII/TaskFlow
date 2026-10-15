"""Pydantic v2 schemas for Kanban Boards, Lists, Tasks, and OCC moves."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.kanban.models import TaskPriority


class BoardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class BoardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None = None
    created_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TaskBriefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    priority: str
    version: int
    ordering_key: str
    assignee_id: uuid.UUID | None = None
    due_date: datetime | None = None


class ListTreeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    ordering_key: str
    version: int
    tasks: list[TaskBriefRead] = []


class BoardTreeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None = None
    lists: list[ListTreeRead] = []


class ListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    prev_list_id: uuid.UUID | None = None


class ListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    board_id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    ordering_key: str
    version: int
    created_at: datetime
    updated_at: datetime


class ListMoveRequest(BaseModel):
    prev_list_id: uuid.UUID | None = None
    next_list_id: uuid.UUID | None = None
    expected_version: int


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    prev_task_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    due_date: datetime | None = None


class TaskUpdate(BaseModel):
    expected_version: int
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    priority: TaskPriority | None = None
    assignee_id: uuid.UUID | None = None
    due_date: datetime | None = None


class TaskMoveRequest(BaseModel):
    target_list_id: uuid.UUID
    prev_task_id: uuid.UUID | None = None
    next_task_id: uuid.UUID | None = None
    expected_version: int


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    list_id: uuid.UUID
    board_id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    description: str | None = None
    priority: str
    ordering_key: str
    version: int
    assignee_id: uuid.UUID | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None
    created_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
