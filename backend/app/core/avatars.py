"""
Shared avatar_url validation for User and Team (both plain unbounded
`String` columns, see their models -- there's no DB-level length limit
to lean on). avatar_url holds one of two shapes:

  - "ffc-avatar:<id>" -- one of the built-in icon avatars (frontend's
    TEAM_AVATARS), tiny, never worth validating length on.
  - "data:image/...;base64,..." -- a user-uploaded photo. The frontend
    (Avatar Editor component) center-crops and downsizes to 256x256
    JPEG before ever sending one of these, which lands well under this
    cap in practice -- this exists to reject someone hitting the API
    directly with an unprocessed multi-megabyte image rather than to be
    a limit real usage should ever brush against.
"""
from fastapi import HTTPException

# ~512KB of base64 text (base64 inflates raw bytes by ~4/3, so this
# still comfortably covers a several-hundred-KB source image even
# without the frontend's resize).
MAX_AVATAR_URL_LENGTH = 700_000


def validate_avatar_url(avatar_url: str | None) -> None:
    if avatar_url is not None and len(avatar_url) > MAX_AVATAR_URL_LENGTH:
        raise HTTPException(status_code=422, detail="Avatar image is too large.")
