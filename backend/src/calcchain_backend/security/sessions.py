from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass


@dataclass(slots=True)
class Session:
    token_hash: str
    created_at: float
    expires_at: float


class SessionManager:
    """In-memory browser sessions for the first LAN auth implementation."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions_by_hash: dict[str, Session] = {}

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create(self) -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        now = time.time()
        session = Session(
            token_hash=token_hash,
            created_at=now,
            expires_at=now + self._ttl_seconds,
        )
        self._sessions_by_hash[token_hash] = session
        return token, session

    def is_valid(self, token: str | None) -> bool:
        if not token:
            return False

        token_hash = self._hash_token(token)
        session = self._sessions_by_hash.get(token_hash)
        if session is None:
            return False

        if session.expires_at < time.time():
            self._sessions_by_hash.pop(token_hash, None)
            return False

        return True

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        self._sessions_by_hash.pop(self._hash_token(token), None)
