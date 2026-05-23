from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
from typing import Any


class JobStatus(StrEnum):
    BUILT = 'Built'
    SUCCEEDED = 'Succeeded'
    FAILED = 'Failed'
    TIMEOUT = 'Timeout'
    CANCELLED = 'Cancelled'
    KILLED = 'Killed'
    PUBLISHED = 'Published'


class RunStatus(StrEnum):
    SUCCEEDED = 'Succeeded'
    FAILED = 'Failed'
    TIMEOUT = 'Timeout'
    CANCELLED = 'Cancelled'
    KILLED = 'Killed'
    

@dataclass(frozen=True)
class RuntimeStatus:
    job_status: JobStatus
    updated_at: str
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @classmethod
    def built(cls, *, warnings: list[str] | None = None, blockers: list[str] | None = None) -> 'RuntimeStatus':
        return cls(
            job_status=JobStatus.BUILT,
            updated_at=datetime.now(timezone.utc).isoformat(),
            warnings=list(warnings or []),
            blockers=list(blockers or []),
        )

    @classmethod
    def from_run_status(
        cls,
        run_status: RunStatus,
        *,
        warnings: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> 'RuntimeStatus':
        job_status = {
            RunStatus.SUCCEEDED: JobStatus.SUCCEEDED,
            RunStatus.FAILED: JobStatus.FAILED,
            RunStatus.TIMEOUT: JobStatus.TIMEOUT,
            RunStatus.CANCELLED: JobStatus.CANCELLED,
            RunStatus.KILLED: JobStatus.KILLED,
        }[run_status]
        return cls(
            job_status=job_status,
            updated_at=datetime.now(timezone.utc).isoformat(),
            warnings=list(warnings or []),
            blockers=list(blockers or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'job_status': self.job_status.value,
            'updated_at': self.updated_at,
            'warnings': list(self.warnings),
            'blockers': list(self.blockers),
        }


def write_runtime_status(path: Path, status: RuntimeStatus) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(status.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
