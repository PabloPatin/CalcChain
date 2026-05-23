from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..common.hash import sha256_dict
from .config import BuildConfig
from .lock import BuildLock, LockMetadata


@dataclass(frozen=True)
class BuildPlan:
    lock: BuildLock
    entries: list[Any]
    warnings: list[str]


def create_build_lock(build: BuildConfig, registry, rules) -> BuildLock:
    build_data = build.to_dict()
    return BuildLock(
        schema_version=build.schema_version,
        lock=LockMetadata(
            created_at=datetime.now(timezone.utc).isoformat(),
            created_from='build.toml',
            source_sha256=sha256_dict(build_data),
        ),
        build=build.build,
        code=build.code,
        inputs=build.inputs,
        rules=build.rules,
    )
