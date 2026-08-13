from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class InviteCreateRequest(BaseModel):
    emails: List[str] = Field(min_length=1, max_length=20)
    message: Optional[str] = None


class InviteRead(BaseModel):
    id: str
    invited_email: str
    status: str  # includes the derived "expired" display value, not just InviteStatus
    created_at: datetime
    expires_at: datetime
    accepted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class InviteLandingRead(BaseModel):
    """What the public, no-auth-required GET /invites/{token} landing page
    gets -- league name/description and who invited them, not the full
    league record (this is reachable by anyone holding the link, logged
    in or not)."""
    league_id: str
    league_name: str
    league_description: Optional[str] = None
    inviter_username: str
    personal_message: Optional[str] = None
    usable: bool  # false if already accepted/revoked/expired
