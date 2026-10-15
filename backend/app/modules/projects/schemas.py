"""Pydantic v2 schemas for Projects and Project Memberships."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.projects.models import ProjectRole, ProjectVisibility
from app.modules.users.schemas import UserBrief

KEY_REGEX = re.compile(r"^[A-Z0-9]{2,20}$")


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    key: str = Field(..., min_length=2, max_length=20)
    description: str | None = Field(default=None, max_length=2000)
    visibility: ProjectVisibility = ProjectVisibility.ORG_PUBLIC

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        clean = v.strip().upper()
        if not KEY_REGEX.match(clean):
            raise ValueError("Key must be 2-20 uppercase alphanumeric characters")
        return clean


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    visibility: ProjectVisibility | None = None
    is_archived: bool | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    key: str
    description: str | None
    visibility: str
    is_archived: bool
    created_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ProjectMemberCreate(BaseModel):
    user_id: uuid.UUID
    project_role: ProjectRole = ProjectRole.MEMBER


class ProjectMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    project_role: str
    created_at: datetime
    user: UserBrief | None = None


class ProjectMemberListResponse(BaseModel):
    items: list[ProjectMemberRead]
