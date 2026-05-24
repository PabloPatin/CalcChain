from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..common.errors import ReportError
from ..utils.json import read_json
from ..manifest import Manifest
from .types import (
    ReportAdapter,
    ReportContext,
    ReportDescriptor,
    ReportOwner,
    ReportRequest,
    ReportResult,
    freeze_manifest,
)


@dataclass(frozen=True)
class RegisteredReportCapability:
    adapter: ReportAdapter
    owner_id: str | None = None
    owner_version: str | None = None


class ReportRegistry:
    def __init__(self, entries: Mapping[str, RegisteredReportCapability] | None = None):
        self._entries: dict[str, RegisteredReportCapability] = dict(entries or {})

    @classmethod
    def from_runtime(cls, runtime=None) -> 'ReportRegistry':
        if runtime is None:
            return cls()
        entries: dict[str, RegisteredReportCapability] = {}
        for key, record in getattr(runtime, 'capabilities', {}).items():
            if _capability_namespace(key) != 'report':
                continue
            report_id = _capability_id(key)
            if report_id in entries:
                raise ReportError(f"report id {report_id!r} is already registered")
            adapter = _validate_report_adapter(report_id, _record_adapter(record))
            entries[report_id] = RegisteredReportCapability(
                adapter=adapter,
                owner_id=_record_owner_id(record),
                owner_version=_record_owner_version(record),
            )
        return cls(entries)

    def register(
        self,
        report_id: str,
        adapter: ReportAdapter,
        *,
        owner_id: str | None = None,
        owner_version: str | None = None,
    ) -> None:
        _validate_report_id(report_id)
        if report_id in self._entries:
            raise ReportError(f"report id {report_id!r} is already registered")
        self._entries[report_id] = RegisteredReportCapability(
            adapter=_validate_report_adapter(report_id, adapter),
            owner_id=owner_id,
            owner_version=owner_version,
        )

    def list_reports(self) -> list[ReportDescriptor]:
        return [self.describe(report_id) for report_id in sorted(self._entries)]

    def describe(self, report_id: str) -> ReportDescriptor:
        entry = self._entry_for(report_id)
        adapter = entry.adapter
        try:
            descriptor = adapter.describe(self._context(report_id, entry, manifest={}))
        except Exception as err:
            raise ReportError(_sanitize_report_error(f'report capability describe failed: {err}')) from err
        if not isinstance(descriptor, ReportDescriptor):
            raise ReportError(f"report {report_id!r} describe must return ReportDescriptor")
        if descriptor.id != report_id:
            raise ReportError(f"report {report_id!r} describe returned mismatched id")
        return descriptor

    def render(self, request: ReportRequest, manifest: Mapping[str, Any]) -> ReportResult:
        entry = self._entry_for(request.report_id)
        adapter = entry.adapter
        context = self._context(request.report_id, entry, manifest=freeze_manifest(manifest))
        try:
            result = adapter.render(request, context)
        except Exception as err:
            raise ReportError(_sanitize_report_error(f'report capability render failed: {err}')) from err
        if not isinstance(result, ReportResult):
            raise ReportError(f"report {request.report_id!r} render must return ReportResult")
        if result.path is not None:
            raise ReportError('report adapters must not choose export paths')
        if result.report_id != request.report_id:
            raise ReportError(f"report {request.report_id!r} render returned mismatched id")
        return result

    def _entry_for(self, report_id: str) -> RegisteredReportCapability:
        try:
            return self._entries[report_id]
        except KeyError as err:
            raise ReportError(f'unsupported report id: {report_id}') from err

    def _context(
        self,
        report_id: str,
        entry: RegisteredReportCapability,
        *,
        manifest: Mapping[str, Any],
    ) -> ReportContext:
        owner = None
        if entry.owner_id is not None:
            owner = ReportOwner(id=entry.owner_id, version=entry.owner_version)
        return ReportContext(owner=owner, capability_id=report_id, manifest=manifest)


def read_report_manifest(path: Path) -> Mapping[str, Any]:
    manifest = Manifest.from_dict(read_json(Path(path)))
    return manifest.to_dict()


def render_report(
    registry: ReportRegistry,
    request: ReportRequest,
    manifest_path: Path,
) -> ReportResult:
    return registry.render(request, read_report_manifest(manifest_path))


def export_report_result(
    result: ReportResult,
    descriptor: ReportDescriptor,
    reports_dir: Path,
    *,
    output_dir: Path | None = None,
) -> ReportResult:
    if result.content is None:
        raise ReportError('report result has no content to export')
    root = Path(reports_dir).resolve()
    destination_dir = root if output_dir is None else Path(output_dir).resolve()
    if not _is_relative_to(destination_dir, root):
        raise ReportError('report export directory must stay under the reports directory')
    destination = destination_dir / _report_filename(result.report_id, descriptor.file_extension)
    if not _is_relative_to(destination.resolve(strict=False).parent, root):
        raise ReportError('report export path must stay under the reports directory')

    destination.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(result.content, bytes):
        destination.write_bytes(result.content)
    else:
        destination.write_text(result.content, encoding='utf-8', newline='\n')
    return ReportResult(
        report_id=result.report_id,
        content=None,
        content_type=result.content_type,
        path=destination,
        metadata=result.metadata,
    )


def export_report(
    registry: ReportRegistry,
    request: ReportRequest,
    manifest_path: Path,
    reports_dir: Path,
    *,
    output_dir: Path | None = None,
) -> ReportResult:
    render_request = ReportRequest(
        report_id=request.report_id,
        manifest_path=request.manifest_path,
        parameters=request.parameters,
        output='return',
    )
    rendered = render_report(registry, render_request, manifest_path)
    descriptor = registry.describe(request.report_id)
    return export_report_result(rendered, descriptor, reports_dir, output_dir=output_dir)


def _report_filename(report_id: str, file_extension: str | None) -> str:
    safe_id = _safe_path_token(report_id)
    extension = file_extension or '.txt'
    if not extension.startswith('.'):
        extension = f'.{extension}'
    extension = _safe_path_token(extension.lstrip('.'))
    return f'{safe_id}.{extension}'


def _safe_path_token(value: str) -> str:
    if not value or any(char in value for char in ('/', '\\', ':')) or value in {'.', '..'}:
        raise ReportError(f'unsafe report path token: {value!r}')
    if '..' in value:
        raise ReportError(f'unsafe report path token: {value!r}')
    return value


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _capability_namespace(key) -> str | None:
    namespace = getattr(key, 'namespace', None)
    return getattr(namespace, 'value', namespace)


def _capability_id(key) -> str:
    capability_id = getattr(key, 'id', None)
    if not isinstance(capability_id, str) or not capability_id:
        raise ReportError('report capability key must have a non-empty id')
    return capability_id


def _record_adapter(record) -> object:
    if hasattr(record, 'capability'):
        return record.capability
    if hasattr(record, 'adapter'):
        return record.adapter
    raise ReportError('report capability record must expose adapter')


def _validate_report_adapter(report_id: str, adapter: object) -> ReportAdapter:
    if not isinstance(adapter, ReportAdapter):
        raise ReportError(f"report {report_id!r} must implement ReportAdapter")
    return adapter


def _record_owner_id(record) -> str | None:
    owner_id = getattr(record, 'owner_id', None)
    if owner_id is not None:
        return owner_id
    owner = getattr(record, 'owner', None)
    if isinstance(owner, str):
        return owner
    return getattr(owner, 'id', None)


def _record_owner_version(record) -> str | None:
    owner = getattr(record, 'owner', None)
    return getattr(owner, 'version', None)


def _validate_report_id(report_id: str) -> None:
    if not isinstance(report_id, str) or not report_id:
        raise ReportError('report id must be a non-empty string')


def _sanitize_report_error(message: str) -> str:
    return str(message)
