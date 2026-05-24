from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobLayout:
    job_dir: Path
    work_dir: Path
    service_dir: Path
    rules_dir: Path
    logs_dir: Path
    frozen_inputs_dir: Path
    snapshots_dir: Path
    build_artifacts_dir: Path
    publish_artifacts_dir: Path
    reports_dir: Path
    manifest_path: Path

    @classmethod
    def from_job_dir(cls, job_dir: Path) -> 'JobLayout':
        job_dir = Path(job_dir)
        service_dir = job_dir / '.calcchain'
        return cls(
            job_dir=job_dir,
            work_dir=job_dir / 'work',
            service_dir=service_dir,
            rules_dir=service_dir / 'rules',
            logs_dir=service_dir / 'logs',
            frozen_inputs_dir=service_dir / 'frozen_inputs',
            snapshots_dir=service_dir / 'snapshots',
            build_artifacts_dir=service_dir / 'build',
            publish_artifacts_dir=service_dir / 'publish',
            reports_dir=service_dir / 'reports',
            manifest_path=service_dir / 'manifest.json',
        )
