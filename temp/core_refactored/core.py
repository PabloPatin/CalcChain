from pathlib import Path
from typing import Any

from calcchain_capabilities import ReportDescriptor, ReportRequest, ReportResult
from calcchain_core.build.builder import BuildResult
from calcchain_core.cleanup.cleanup import CleanupResult
from calcchain_core.models import Manifest, PublishLock
from calcchain_core.publish.publish import PublishResult
from calcchain_core.reports.registry import ReportRegistry
from calcchain_core.restore.restore import RestoreRequest, RestoreResult

from .auth.auth_service import AuthService as AuthServiceProtocol, NoAuthService
from .build.config import BuildConfig, read_toml, write_toml
from .build.lock import BuildLock
from .build.plan import BuildPlan, create_build_lock
from .capabilities.runtime import RuntimeCapabilities
from .io.source import SourceRegistry
from .io.target import TargetRegistry
from .workspace.layout import JobLayout


class CalculationCore:
    def __init__(
        self,
        job_dir: Path,
        *,
        runtime: RuntimeCapabilities | None = None,
        auth_service: AuthServiceProtocol | None = None,
    ):
        self.job_dir = Path(job_dir)
        self.layout = JobLayout.from_job_dir(self.job_dir)
        self.auth_service = auth_service if auth_service is not None else NoAuthService()
        self.source_registry = SourceRegistry.from_runtime(runtime, auth=self.auth_service)
        self.target_registry = TargetRegistry.from_runtime(runtime, auth=self.auth_service)
        self.report_registry = ReportRegistry.from_runtime(runtime)
        self._last_plan: BuildPlan | None = None
        self._last_build_result: BuildResult | None = None

    def create_build_lock(self, build_path: Path | None = None) -> BuildLock:
        path = Path(build_path) if build_path is not None else self.job_dir / 'build.toml'
        config = BuildConfig.from_dict(read_toml(path), default_build_name=path.parent.name)
        lock = create_build_lock(config, self.source_registry, self._read_rules_optional())
        write_toml(lock.to_dict(), self.job_dir / 'build.lock.toml')
        return lock

    def validate_build(self) -> BuildPlan:
        ...

    def build(self, *, dry_run: bool = False):
        ...

    def run(self, run_path: Path | None = None) -> Manifest:
        ...

    def create_publish_lock(self, publish_path: Path | None = None) -> PublishLock:
        ...

    def publish(self, publish_path: Path | None = None, *, dry_run: bool = False) -> PublishResult:
        ...

    def restore(self, request: RestoreRequest) -> RestoreResult:
        ...

    def cleanup(self, *, dry_run: bool = False) -> CleanupResult:
        ...

    def list_reports(self) -> list[ReportDescriptor]:
        ...

    def render_report(self, request: ReportRequest) -> ReportResult:
        ...

    def export_report(self, request: ReportRequest, output_dir: Path | None = None) -> ReportResult:
        ...

    def _render_report_content(self, request: ReportRequest) -> ReportResult:
        ...

    def _read_rules_optional(self):
        ...

    def _rules_path_optional(self) -> Path | None:
        ...

    def _job_context(self) -> dict[str, Any]:
        ...

    def _load_build_result(self) -> BuildResult:
        ...
