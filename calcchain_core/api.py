from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from calcchain_core.auth import NoAuthService
from calcchain_core.build_plan import BuildPlan, create_build_lock, validate_build_lock
from calcchain_core.builder import BuildResult, EnvironmentBuilder, RulesArtifact
from calcchain_core.cleanup import CleanupResult, cleanup_work_dir
from calcchain_core.config import (
    read_build,
    read_build_lock,
    read_publish,
    read_rules,
    read_run,
    write_build_lock,
    write_manifest,
    write_publish_lock,
)
from calcchain_core.layout import JobLayout
from calcchain_core.manifest import ManifestWriter
from calcchain_core.maps import FileSetMap
from calcchain_core.models import (
    BuildLock,
    FileMapEntry,
    Manifest,
    PublishLock,
    RuleUse,
    RunConfig,
    SourceRef,
)
from calcchain_core.output_classifier import classify_files
from calcchain_core.plugins.manager import PluginRuntimeSet
from calcchain_core.publish import PublishResult, build_publish_plan, create_publish_lock, execute_publish_plan
from calcchain_core.restore import RestoreRequest, RestoreResult, restore_from_manifest
from calcchain_core.runner import CancelToken, ProcessRunner, RunResult
from calcchain_core.snapshot import Snapshot, SnapshotEntry
from calcchain_core.sources import SourceRegistry
from calcchain_core.targets import TargetRegistry


class CalculationCore:
    def __init__(
        self,
        job_dir: Path,
        *,
        plugin_runtime: PluginRuntimeSet | None = None,
        source_registry: SourceRegistry | None = None,
        target_registry: TargetRegistry | None = None,
        auth_service: object | None = None,
    ):
        self.job_dir = Path(job_dir)
        self.layout = JobLayout.from_job_dir(self.job_dir)
        self.auth_service = auth_service if auth_service is not None else NoAuthService()
        self.source_registry = source_registry or SourceRegistry.from_runtime(plugin_runtime, auth=self.auth_service)
        self.target_registry = target_registry or TargetRegistry.from_runtime(plugin_runtime, auth=self.auth_service)
        self._last_plan: BuildPlan | None = None
        self._last_build_result: BuildResult | None = None

    def create_build_lock(self, build_path: Path | None = None) -> BuildLock:
        path = Path(build_path) if build_path is not None else self.job_dir / 'build.toml'
        lock = create_build_lock(read_build(path), self.source_registry, self._read_rules_optional())
        write_build_lock(lock, self.job_dir / 'build.lock.toml')
        return lock

    def validate_build(self) -> BuildPlan:
        lock = read_build_lock(self.job_dir / 'build.lock.toml')
        plan = validate_build_lock(lock, self.source_registry, self._read_rules_optional())
        self._last_plan = plan
        return plan

    def build(self, *, dry_run: bool = False):
        plan = self._last_plan or self.validate_build()
        result = EnvironmentBuilder(self.source_registry, rules_file_path=self._rules_path_optional()).build(
            self.layout,
            plan,
            dry_run=dry_run,
        )
        self._last_build_result = result
        if not dry_run:
            manifest = ManifestWriter.create_after_build(
                self._job_context(),
                result,
                {'build': self.layout.snapshots_dir / 'build_snapshot.json'},
            )
            write_manifest(manifest, self.layout.manifest_path)
        return result

    def run(self, run_path: Path | None = None) -> Manifest:
        request = read_run(Path(run_path) if run_path is not None else self.job_dir / 'run.toml')
        plan = self._last_plan or self.validate_build()
        build_result = self._last_build_result or self._load_build_result()
        pre_run = EnvironmentBuilder(self.source_registry, rules_file_path=self._rules_path_optional()).check_pre_run(
            self.layout,
            build_result,
            plan,
        )
        if pre_run.blockers:
            from calcchain_core.errors import RunExecutionError

            raise RunExecutionError('; '.join(pre_run.blockers))
        run_result = ProcessRunner().run(self.layout, request)
        file_groups = classify_files(
            build_result,
            pre_run.pre_run_snapshot,
            run_result.post_run_snapshot,
            self._read_rules_optional(),
        )
        manifest_build_result = _with_frozen_inputs(build_result, pre_run.frozen_inputs)
        manifest = ManifestWriter.create_after_run(
            self._job_context(),
            manifest_build_result,
            run_result,
            file_groups,
            {
                'build': self.layout.snapshots_dir / 'build_snapshot.json',
                'pre_run': self.layout.snapshots_dir / 'pre_run_snapshot.json',
                'post_run': self.layout.snapshots_dir / 'post_run_snapshot.json',
            },
        )
        write_manifest(manifest, self.layout.manifest_path)
        return manifest

    def create_publish_lock(self, publish_path: Path | None = None) -> PublishLock:
        path = Path(publish_path) if publish_path is not None else self.job_dir / 'publish.toml'
        lock = create_publish_lock(read_publish(path), self.target_registry)
        write_publish_lock(lock, self.job_dir / 'publish.lock.toml')
        return lock

    def publish(self, publish_path: Path | None = None, *, dry_run: bool = False) -> PublishResult:
        lock = self.create_publish_lock(publish_path)
        manifest = _read_manifest(self.layout.manifest_path)
        plan = build_publish_plan(manifest, lock, self._read_rules_optional())
        plan = replace(plan, target_registry=self.target_registry)
        result = execute_publish_plan(plan, dry_run=dry_run)
        if not dry_run:
            write_manifest(result.updated_manifest, self.layout.manifest_path)
        return result

    def restore(self, request: RestoreRequest) -> RestoreResult:
        return restore_from_manifest(request, self.source_registry)

    def cleanup(self, *, dry_run: bool = False) -> CleanupResult:
        return cleanup_work_dir(self.layout, dry_run=dry_run)

    def _read_rules_optional(self):
        path = self._rules_path_optional()
        return read_rules(path) if path is not None else None

    def _rules_path_optional(self) -> Path | None:
        path = self.job_dir / 'rules.json'
        return path if path.is_file() else None

    def _job_context(self) -> dict[str, Any]:
        return {
            'id': self.job_dir.name,
            'job_dir': self.job_dir,
            'layout': self.layout,
            'build_lock_path': self.layout.build_artifacts_dir / 'build_lock.json',
        }

    def _load_build_result(self) -> BuildResult:
        code_set = _file_set_from_dict(_read_json(self.layout.build_artifacts_dir / 'code_map.json'))
        input_sets = [
            _file_set_from_dict(item)
            for item in _read_json(self.layout.build_artifacts_dir / 'input_maps.json')
        ]
        rules_artifact = None
        rules_path = self.layout.build_artifacts_dir / 'rules_artifact.json'
        if rules_path.is_file():
            rules_data = _read_json(rules_path)
            rules_artifact = RulesArtifact(path=rules_data['path'], sha256=rules_data.get('sha256'))
        return BuildResult(
            code_set=code_set,
            input_sets=input_sets,
            build_snapshot=_snapshot_from_dict(_read_json(self.layout.snapshots_dir / 'build_snapshot.json')),
            rules_artifact=rules_artifact,
        )


def _with_frozen_inputs(build_result: BuildResult, frozen_inputs) -> SimpleNamespace:
    return SimpleNamespace(
        code_set=build_result.code_set,
        input_sets=build_result.input_sets,
        build_snapshot=build_result.build_snapshot,
        rules_artifact=build_result.rules_artifact,
        warnings=build_result.warnings,
        pre_run_snapshot=build_result.pre_run_snapshot,
        runtime_status=build_result.runtime_status,
        dry_run=build_result.dry_run,
        preview=build_result.preview,
        frozen_inputs=frozen_inputs,
    )


def _read_manifest(path: Path) -> Manifest:
    with Path(path).open('r', encoding='utf-8') as file:
        return Manifest.from_dict(json.load(file))


def _read_json(path: Path):
    with Path(path).open('r', encoding='utf-8') as file:
        return json.load(file)


def _file_set_from_dict(data: dict[str, Any]) -> FileSetMap:
    source = SourceRef.from_dict(data['source']) if isinstance(data.get('source'), dict) else None
    sources = [SourceRef.from_dict(item) for item in data.get('sources') or []]
    rules = RuleUse.from_dict(data['rules']) if isinstance(data.get('rules'), dict) else None
    return FileSetMap(
        name=data['name'],
        tree_sha256=data['tree_sha256'],
        source=source,
        sources=sources,
        rules=rules,
        map=[FileMapEntry.from_dict(item) for item in data.get('map') or []],
    )


def _snapshot_from_dict(data: dict[str, Any]) -> Snapshot:
    return Snapshot(
        schema_version=data['schema_version'],
        created_at=data['created_at'],
        entries=[
            SnapshotEntry(
                path=item['path'],
                sha256=item['sha256'],
                size=item['size'],
                mtime_utc=item['mtime_utc'],
                kind=item.get('kind', 'file'),
            )
            for item in data.get('entries') or []
        ],
    )


__all__ = ['CalculationCore']
