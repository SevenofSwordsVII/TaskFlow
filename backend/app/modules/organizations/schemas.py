"""Pydantic v2 schemas for Organization and Membership domain."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.organizations.models import OrganizationRole
from app.modules.users.schemas import UserBrief

SLUG_REGEX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)

    @field_validator("slug")
    @classmethod
    def validate_slug_format(cls, v: str) -> str:
        clean = v.strip().lower()
        if not SLUG_REGEX.match(clean):
            raise ValueError(
                "Slug must be lowercase alphanumeric with hyphens, "
                "without leading or trailing hyphens"
            )
        return clean


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    role: str | None = None


class OrganizationMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    created_at: datetime
    updated_at: datetime
    user: UserBrief | None = None


class OrganizationMemberListResponse(BaseModel):
    items: list[OrganizationMemberRead]
    next_cursor: str | None = None


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: uuid.UUID


class MemberAddRequest(BaseModel):
    email: str
    role: OrganizationRole = OrganizationRole.MEMBER

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: OrganizationRole) -> OrganizationRole:
        if v == OrganizationRole.OWNER:
            raise ValueError("Cannot assign OWNER role directly; use ownership transfer.")
        return v


class MemberRoleUpdateRequest(BaseModel):
    role: OrganizationRole


class InvitationCreate(BaseModel):
    email: str = Field(..., max_length=255)
    role: OrganizationRole = OrganizationRole.MEMBER

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email format")
        return clean

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: OrganizationRole) -> OrganizationRole:
        if v == OrganizationRole.OWNER:
            raise ValueError("Cannot invite member with OWNER role; use ownership transfer.")
        return v


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: str
    invited_by_id: uuid.UUID
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    expired_at: datetime | None = None
    invitation_token: str | None = None


class InvitationAcceptRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=128)
