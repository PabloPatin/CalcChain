from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BackendConfig:
    """Runtime settings for the CalcChain backend."""

    host: str = "127.0.0.1"
    port: int = 8765
    lan: bool = False

    # In this first version, auth is required only in LAN mode.
    auth_required: bool = False

    pairing_ttl_seconds: int = 300
    session_ttl_seconds: int = 12 * 60 * 60
    max_pairing_attempts_per_minute: int = 5

    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
