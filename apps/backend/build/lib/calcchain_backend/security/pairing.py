from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class PairingCode:
    code_hash: str
    expires_at: float


@dataclass(slots=True)
class PairingAttemptLimiter:
    max_attempts_per_minute: int
    attempts_by_client: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))

    def allow(self, client_id: str, *, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        window_start = now - 60
        attempts = self.attempts_by_client[client_id]

        while attempts and attempts[0] < window_start:
            attempts.popleft()

        if len(attempts) >= self.max_attempts_per_minute:
            return False

        attempts.append(now)
        return True


class PairingManager:
    """
    Stores a single active one-time pairing code.

    The plain code is returned only to the trusted caller that generated it,
    so it can be printed to the server console. It is never exposed through HTTP.
    """

    def __init__(self, ttl_seconds: int, max_attempts_per_minute: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._active: PairingCode | None = None
        self._limiter = PairingAttemptLimiter(max_attempts_per_minute=max_attempts_per_minute)

    @staticmethod
    def _hash_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def generate(self) -> str:
        code = f"{secrets.randbelow(100_000_000):08d}"
        self._active = PairingCode(
            code_hash=self._hash_code(code),
            expires_at=time.time() + self._ttl_seconds,
        )
        return code

    def has_active_code(self) -> bool:
        return self._active is not None and self._active.expires_at >= time.time()

    def verify_once(self, code: str, *, client_id: str) -> bool:
        if not self._limiter.allow(client_id):
            return False

        active = self._active
        if active is None:
            return False

        now = time.time()
        if active.expires_at < now:
            self._active = None
            return False

        candidate_hash = self._hash_code(code)
        if not secrets.compare_digest(candidate_hash, active.code_hash):
            return False

        # One-time semantics: successful pairing consumes the code.
        self._active = None
        return True
