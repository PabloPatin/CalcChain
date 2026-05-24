from datetime import datetime, timezone
import getpass
import socket
from pathlib import Path

from .build.builder import BuildResult, EnvironmentBuilder, RulesArtifact
from .build.config import BuildConfig
from .build.lock import BuildLock
from .build.plan import BuildPlan, create_build_lock, validate_build_lock
from .capabilities.runtime import RuntimeCapabilities
from .cleanup import CleanupResult, cleanup_work_dir
from .common.errors import RunExecutionError
from .common.hash import sha256_dict
from .io.source import SourceRegistry
from .io.target import TargetRegistry
from .manifest import BuildManifestArtifacts, JobManifestInfo, Manifest, ManifestWriter, write_manifest
from .publish import (
    PublishConfig,
    PublishLock,
    PublishResult,
    build_publish_plan,
    create_publish_lock,
    execute_publish_plan,
)
from .reports import (
    ReportDescriptor,
    ReportRegistry,
    ReportRequest,
    ReportResult,
    export_report_result,
    read_report_manifest,
)
from .restore import RestoreRequest, RestoreResult, restore_from_manifest
from .rules import read_rules
from .run import ProcessRunner, RunConfig
from .run.run_preparation import PreRunPreparer
from .secrets import NoSecretsResolver, SecretsResolver
from .utils.json import read_json
from .utils.toml import read_toml, write_toml
from .workspace.artifacts import artifact_ref
from .workspace.layout import JobLayout
from .workspace.maps import FileSetMap
from .workspace.output_classifier import classify_files
from .workspace.snapshot import read_snapshot


class CalculationCore:
    def __init__(
        self,
        job_dir: Path,
        *,
        runtime: RuntimeCapabilities | None = None,
        source_registry: SourceRegistry | None = None,
        target_registry: TargetRegistry | None = None,
        report_registry: ReportRegistry | None = None,
        secrets_resolver: SecretsResolver | None = None,
    ):
        self.job_dir = Path(job_dir)
        self.layout = JobLayout.from_job_dir(self.job_dir)
        self.secrets_resolver = secrets_resolver if secrets_resolver is not None else NoSecretsResolver()
        self.source_registry = source_registry or SourceRegistry.from_runtime(
            runtime,
            secrets_resolver=self.secrets_resolver,
        )
        self.target_registry = target_registry or TargetRegistry.from_runtime(
            runtime,
            secrets_resolver=self.secrets_resolver,
        )
        self.report_registry = report_registry or ReportRegistry.from_runtime(runtime)
        self._last_plan: BuildPlan | None = None
        self._last_build_result: BuildResult | None = None

    def create_build_lock(self, build_path: Path | None = None) -> BuildLock:
        path = Path(build_path) if build_path is not None else self.job_dir / 'build.toml'
        config = BuildConfig.from_dict(read_toml(path), default_build_name=path.parent.name)
        lock = create_build_lock(config, self.source_registry, self._read_rules_optional())
        write_toml(lock.to_dict(), self.job_dir / 'build.lock.toml')
        return lock

    def validate_build(self) -> BuildPlan:
        lock = BuildLock.from_dict(read_toml(self.job_dir / 'build.lock.toml'))
        plan = validate_build_lock(lock, self.source_registry, self._read_rules_optional())
        self._last_plan = plan
        return plan

    def build(self, *, dry_run: bool = False):
        plan = self._last_plan or self.validate_build()
        result = EnvironmentBuilder(
            self.source_registry,
            rules_file_path=self._rules_path_optional(),
        ).build(self.layout, plan, dry_run=dry_run)
        if not dry_run:
            self._last_build_result = result
            manifest = ManifestWriter.create_after_build(
                self._job_info(),
                result,
                self._build_manifest_artifacts(result, include_run_snapshots=False),
            )
            write_manifest(manifest, self.layout.manifest_path)
        return result

    def run(self, run_path: Path | None = None) -> Manifest:
        path = Path(run_path) if run_path is not None else self.job_dir / 'run.toml'
        request = RunConfig.from_dict(read_toml(path))
        build_result = self._last_build_result or self._load_build_result()
        pre_run = PreRunPreparer(self.source_registry).prepare(self.layout, build_result)
        if pre_run.blockers:
            raise RunExecutionError('; '.join(pre_run.blockers))

        run_result = ProcessRunner(self.secrets_resolver).run(self.layout, request)
        file_groups = classify_files(
            build_result,
            pre_run.pre_run_snapshot,
            run_result.post_run_snapshot,
            self._read_rules_optional(),
        )
        manifest = ManifestWriter.create_after_run(
            self._job_info(),
            build_result,
            run_result,
            file_groups,
            self._build_manifest_artifacts(build_result, include_run_snapshots=True),
            frozen_inputs=pre_run.frozen_inputs,
        )
        write_manifest(manifest, self.layout.manifest_path)
        return manifest

    def create_publish_lock(self, publish_path: Path | None = None) -> PublishLock:
        path = Path(publish_path) if publish_path is not None else self.job_dir / 'publish.toml'
        config = PublishConfig.from_dict(read_toml(path))
        lock = create_publish_lock(config, self.target_registry)
        write_toml(lock.to_dict(), self.job_dir / 'publish.lock.toml')
        return lock

    def publish(self, publish_path: Path | None = None, *, dry_run: bool = False) -> PublishResult:
        lock = self.create_publish_lock(publish_path)
        manifest = Manifest.from_dict(read_json(self.layout.manifest_path))
        plan = build_publish_plan(
            manifest,
            lock,
            self._read_rules_optional(),
            target_registry=self.target_registry,
        )
        result = execute_publish_plan(plan, dry_run=dry_run)
        if not dry_run:
            write_manifest(result.updated_manifest, self.layout.manifest_path)
        return result

    def restore(self, request: RestoreRequest) -> RestoreResult:
        return restore_from_manifest(request, self.source_registry)

    def cleanup(self, *, dry_run: bool = False) -> CleanupResult:
        return cleanup_work_dir(self.layout, dry_run=dry_run)

    def list_reports(self) -> list[ReportDescriptor]:
        return self.report_registry.list_reports()

    def render_report(self, request: ReportRequest) -> ReportResult:
        rendered = self._render_report_content(request)
        if request.output == 'file':
            descriptor = self.report_registry.describe(request.report_id)
            return export_report_result(rendered, descriptor, self.layout.reports_dir)
        return rendered

    def export_report(self, request: ReportRequest, output_dir: Path | None = None) -> ReportResult:
        render_request = ReportRequest(
            report_id=request.report_id,
            manifest_path=request.manifest_path,
            parameters=request.parameters,
            output='return',
        )
        rendered = self._render_report_content(render_request)
        descriptor = self.report_registry.describe(request.report_id)
        return export_report_result(
            rendered,
            descriptor,
            self.layout.reports_dir,
            output_dir=output_dir,
        )

    def _render_report_content(self, request: ReportRequest) -> ReportResult:
        manifest_path = Path(request.manifest_path) if request.manifest_path is not None else self.layout.manifest_path
        manifest = read_report_manifest(manifest_path)
        return self.report_registry.render(request, manifest)

    def _read_rules_optional(self):
        path = self._rules_path_optional()
        return read_rules(path) if path is not None else None

    def _rules_path_optional(self) -> Path | None:
        path = self.job_dir / 'rules.json'
        return path if path.is_file() else None

    def _job_info(self) -> JobManifestInfo:
        return JobManifestInfo(
            id=self.job_dir.name,
            job_dir=self.job_dir,
            created_at=datetime.now(timezone.utc).isoformat(),
            user=_safe_user(),
            hostname=_safe_hostname(),
        )

    def _load_build_result(self) -> BuildResult:
        code_set = FileSetMap.from_dict(read_json(self.layout.build_artifacts_dir / 'code_map.json'))
        input_sets = [
            FileSetMap.from_dict(item)
            for item in read_json(self.layout.build_artifacts_dir / 'input_maps.json')
        ]
        rules_artifact = None
        rules_path = self.layout.build_artifacts_dir / 'rules_artifact.json'
        if rules_path.is_file():
            rules_data = read_json(rules_path)
            rules_artifact = RulesArtifact(
                path=str(rules_data['path']),
                sha256=rules_data.get('sha256'),
            )
        result = BuildResult(
            code_set=code_set,
            input_sets=input_sets,
            build_snapshot=read_snapshot(self.layout.snapshots_dir / 'build_snapshot.json'),
            build_lock_sha256=sha256_dict(read_json(self.layout.build_artifacts_dir / 'build_lock.json')),
            rules_artifact=rules_artifact,
        )
        return result

    def _build_manifest_artifacts(
        self,
        build_result: BuildResult,
        *,
        include_run_snapshots: bool,
    ) -> BuildManifestArtifacts:
        snapshots = {}
        build_snapshot_path = self.layout.snapshots_dir / 'build_snapshot.json'
        if build_snapshot_path.is_file():
            snapshots['build'] = artifact_ref(build_snapshot_path)
        if include_run_snapshots:
            pre_run_snapshot_path = self.layout.snapshots_dir / 'pre_run_snapshot.json'
            post_run_snapshot_path = self.layout.snapshots_dir / 'post_run_snapshot.json'
            if pre_run_snapshot_path.is_file():
                snapshots['pre_run'] = artifact_ref(pre_run_snapshot_path)
            if post_run_snapshot_path.is_file():
                snapshots['post_run'] = artifact_ref(post_run_snapshot_path)

        build_lock = None
        build_lock_path = self.layout.build_artifacts_dir / 'build_lock.json'
        if build_lock_path.is_file():
            build_lock = artifact_ref(build_lock_path)

        rules = None
        if build_result.rules_artifact is not None:
            rules_path = self.layout.job_dir / build_result.rules_artifact.path
            if rules_path.is_file():
                rules = artifact_ref(rules_path)

        return BuildManifestArtifacts(
            build_lock=build_lock,
            rules=rules,
            snapshots=snapshots,
        )


def _safe_user() -> str | None:
    try:
        return getpass.getuser()
    except Exception:
        return None


def _safe_hostname() -> str | None:
    try:
        return socket.gethostname()
    except Exception:
        return None
