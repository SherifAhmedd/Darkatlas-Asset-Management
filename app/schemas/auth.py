from uuid import UUID
from pydantic import BaseModel, field_validator


class UserRegisterRequest(BaseModel):
    """Schema for registering a new user."""

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Username must not be empty")
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserLoginRequest(BaseModel):
    """Schema for user login."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Schema for the JWT token response returned on login/register."""

    access_token: str
    token_type: str = "bearer"


class CurrentUser(BaseModel):
    """Represents the authenticated user context injected by deps.py."""

    id: UUID
    username: str
    tenant_id: UUID

    model_config = {"from_attributes": True}
