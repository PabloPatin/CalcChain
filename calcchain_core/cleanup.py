from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil

from calcchain_core.errors import CleanupError
from calcchain_core.layout import JobLayout


@dataclass(frozen=True)
class CleanupResult:
    removed_paths: list[str] = field(default_factory=list)
    status: str = 'cleaned'
    dry_run: bool = False


def cleanup_work_dir(layout: JobLayout, *, dry_run: bool = False) -> CleanupResult:
    work_dir = Path(layout.work_dir)
    _ensure_safe_work_dir(layout, work_dir)
    if not work_dir.exists():
        return CleanupResult(status='already_clean', dry_run=dry_run)

    removed = sorted(path.relative_to(work_dir).as_posix() for path in work_dir.iterdir())
    if dry_run:
        return CleanupResult(removed_paths=removed, status='planned', dry_run=True)

    for path in sorted(work_dir.iterdir(), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    work_dir.mkdir(parents=True, exist_ok=True)
    return CleanupResult(removed_paths=removed, status='cleaned', dry_run=False)


def _ensure_safe_work_dir(layout: JobLayout, work_dir: Path) -> None:
    job_dir = Path(layout.job_dir).resolve(strict=False)
    service_dir = Path(layout.service_dir).resolve(strict=False)
    candidate = work_dir.resolve(strict=False)
    try:
        candidate.relative_to(job_dir)
    except ValueError as err:
        raise CleanupError(f'work dir is outside job dir: {work_dir}') from err
    if candidate == job_dir:
        raise CleanupError('work dir must not be the job dir')
    if candidate == service_dir:
        raise CleanupError('work dir must not be the service dir')
    try:
        candidate.relative_to(service_dir)
    except ValueError:
        return
    raise CleanupError('work dir must not be inside the service dir')
