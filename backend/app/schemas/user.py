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
