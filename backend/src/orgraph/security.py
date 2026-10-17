from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings, get_settings

API_KEY_PREFIX = "ogk_"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, InvalidHashError):
        return False


def create_access_token(user_id: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str, settings: Settings | None = None) -> str | None:
    """Return the user id, or None if the token is invalid or expired."""
    settings = settings or get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"]).get("sub")
    except jwt.PyJWTError:
        return None


def generate_api_key() -> tuple[str, str, str]:
    """Return (full key, display prefix, sha256 hash). Only the hash is stored."""
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return key, key[:12], hash_api_key(key)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _fernet(settings: Settings) -> Fernet:
    if settings.encryption_key:
        return Fernet(settings.encryption_key)
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secrets(secrets_: dict[str, Any], settings: Settings | None = None) -> str:
    return _fernet(settings or get_settings()).encrypt(json.dumps(secrets_).encode()).decode()


def decrypt_secrets(token: str, settings: Settings | None = None) -> dict[str, Any]:
    """Raises ValueError when the token was encrypted with a different key."""
    if not token:
        return {}
    try:
        return json.loads(_fernet(settings or get_settings()).decrypt(token.encode()))
    except InvalidToken as exc:
        raise ValueError("stored secrets cannot be decrypted with the current key") from exc
