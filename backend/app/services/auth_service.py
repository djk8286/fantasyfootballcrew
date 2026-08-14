"""
Authentication service using bcrypt directly instead of passlib.
Avoids the passlib/bcrypt compatibility issue on Windows.
Uses PyJWT for token generation.
"""
import hashlib
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
import jwt
from app.core.config import settings


def hash_password(password: str) -> str:
    """bcrypt, cost factor 12 (library default). Replaces a previous
    SHA-256 implementation -- see needs_rehash() for how existing
    accounts transparently migrate to this on their next login."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def needs_rehash(hashed_password: str) -> bool:
    """True for a hash still in the old SHA-256 `salt:hash` format --
    bcrypt output always starts with a fixed `$2` prefix, so this is
    an unambiguous format check, not a guess."""
    return not hashed_password.startswith("$2")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash. Accepts both current
    (bcrypt) and legacy (salted SHA-256) hash formats so existing
    accounts keep working -- login() transparently rehashes to bcrypt
    on successful verification of a legacy hash, so this legacy branch
    stops being hit for that user going forward. No forced reset."""
    if not needs_rehash(hashed_password):
        try:
            return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
        except ValueError:
            return False
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
