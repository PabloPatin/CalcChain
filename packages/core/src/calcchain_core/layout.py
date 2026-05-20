from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PublicationServiceLayout:
    root_name: str = '_calcchain'
    frozen_inputs_dir_name: str = 'frozen_inputs'
    logs_dir_name: str = 'logs'
    rules_dir_name: str = 'rules'
    snapshots_dir_name: str = 'snapshots'
    publication_dir_name: str = 'publication'
    manifest_name: str = 'manifest.json'
    build_lock_name: str = 'build.lock.toml'
    publish_lock_name: str = 'publish.lock.toml'

    @property
    def frozen_inputs_path(self) -> Path:
        return Path(self.root_name) / self.frozen_inputs_dir_name

    @property
    def manifest_path(self) -> Path:
        return Path(self.root_name) / self.manifest_name

    @property
    def logs_path(self) -> Path:
        return Path(self.root_name) / self.logs_dir_name

    @property
    def rules_path(self) -> Path:
        return Path(self.root_name) / self.rules_dir_name

    @property
    def snapshots_path(self) -> Path:
        return Path(self.root_name) / self.snapshots_dir_name

    @property
    def publication_path(self) -> Path:
        return Path(self.root_name) / self.publication_dir_name


@dataclass(frozen=True)
class JobLayout:
    job_dir: Path  # Рабочее окружение
    work_dir: Path  # Папка расчёта
    service_dir: Path  # Папка со служебными файлами
    rules_dir: Path
    logs_dir: Path
    frozen_inputs_dir: Path
    snapshots_dir: Path
    build_artifacts_dir: Path 
    publication_artifacts_dir: Path
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
            publication_artifacts_dir=service_dir / 'publication',
            reports_dir=service_dir / 'reports',
            manifest_path=service_dir / 'manifest.json',
        )
