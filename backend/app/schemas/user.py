from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class UserCreate(BaseModel):
    email: str
    username: str
    password: Optional[str] = Field(default=None, min_length=8)
    provider: str = "email"


class UserLogin(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class UserRead(BaseModel):
    id: str
    email: str
    username: str
    avatar_url: Optional[str] = None
    provider: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserPublic(BaseModel):
    """What a third party gets back for GET /users/{id} -- no email. A
    user_id shows up all over otherwise-public reads (Team.owner_id,
    League.commissioner_id, ...), so anyone could look one up; email is
    PII and has no business being reachable that way just because you
    know someone's user_id. UserRead (full record, including email)
    stays reserved for GET /users/me -- looking at your own account."""
    id: str
    username: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True
