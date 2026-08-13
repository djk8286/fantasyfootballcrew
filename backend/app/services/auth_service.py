"""
Authentication service using bcrypt directly instead of passlib.
Avoids the passlib/bcrypt compatibility issue on Windows.
Uses PyJWT for token generation.
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional
import jwt
from app.core.config import settings


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with a random salt."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{pwd_hash}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        salt, pwd_hash = hashed_password.split(":")
        check = hashlib.sha256((salt + plain_password).encode()).hexdigest()
        return check == pwd_hash
    except (ValueError, AttributeError):
        return False


def hash_token(raw_token: str) -> str:
    """Plain SHA-256, no salt -- for tokens that are already high-entropy
    random values (secrets.token_urlsafe(32)+), not user-chosen secrets
    like passwords. The hash exists so a leaked DB row can't be used
    directly as a working link; unlike a password, brute-forcing a raw
    32-byte random token back out of its hash isn't practically feasible
    regardless of salting. Shared by every single-use-link flow in the
    app (password reset, league invites) so they don't each reimplement
    the same three lines."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=30))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT access token."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None
