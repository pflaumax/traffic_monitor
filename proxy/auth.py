import logging
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from proxy.config import settings

logger = logging.getLogger(__name__)

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def _hash_password(plain: str) -> bytes:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt())


def _verify_password(plain: str, hashed: bytes) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed)


_ADMIN_PASSWORD_HASH: bytes = _hash_password(settings.admin_password)
_DUMMY_HASH: bytes = _hash_password("dummy-sentinel-that-will-never-match")


def create_access_token(subject: str) -> str:
    """Create a signed JWT with a configurable expiry."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def authenticate_user(username: str, password: str) -> bool:
    """Return True if the credentials match the configured admin account."""
    username_ok = username == settings.admin_username
    target_hash = _ADMIN_PASSWORD_HASH if username_ok else _DUMMY_HASH
    password_ok = _verify_password(password, target_hash)
    return username_ok and password_ok


async def require_auth(token: str = Depends(_oauth2_scheme)) -> str:
    """FastAPI dependency — validates JWT and returns the subject (username)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        subject: str | None = payload.get("sub")
        if subject is None:
            raise credentials_exception
    except JWTError:
        logger.warning("JWT validation failed")
        raise credentials_exception from None
    return subject
