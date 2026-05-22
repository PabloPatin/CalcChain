from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from calcchain_core.common.errors import ReportError
from calcchain_core.models import Manifest
from calcchain_capabilities import CapabilityOwner, ReportContext, ReportDescriptor, ReportRequest, ReportResult
from calcchain_capabilities.diagnostics import redact_secrets
from calcchain_capabilities import PluginRuntimeSet


@dataclass(frozen=True)
class RegisteredReportCapability:
    adapter: object
    plugin_id: str | None


class ReportRegistry:
    def __init__(self, entries: Mapping[str, RegisteredReportCapability] | None = None):
        self._entries: dict[str, RegisteredReportCapability] = dict(entries or {})

    @classmethod
    def from_runtime(cls, runtime: PluginRuntimeSet | None) -> 'ReportRegistry':
        entries: dict[str, RegisteredReportCapability] = {}
        if runtime is None:
            return cls(entries)
        for key, record in runtime.capabilities.items():
            if key.namespace != 'report':
                continue
            if key.id in entries:
                raise ReportError(f"report id {key.id!r} is already registered")
            entries[key.id] = RegisteredReportCapability(record.capability, plugin_id=record.owner_id)
        return cls(entries)

    def list_reports(self) -> list[ReportDescriptor]:
        descriptors = []
        for report_id in sorted(self._entries):
            descriptors.append(self.describe(report_id))
        return descriptors

    def describe(self, report_id: str) -> ReportDescriptor:
        entry = self._entry_for(report_id)
        adapter = entry.adapter
        if not hasattr(adapter, 'describe'):
            raise ReportError(f"report {report_id!r} does not implement describe")
        context = self._context(report_id, entry, manifest={})
        try:
            descriptor = adapter.describe(context)
        except Exception as err:
            raise ReportError(_sanitize_report_error(f'plugin report describe failed: {err}')) from err
        if not isinstance(descriptor, ReportDescriptor):
            raise ReportError(f"report {report_id!r} describe must return ReportDescriptor")
        if descriptor.id != report_id:
            raise ReportError(f"report {report_id!r} describe returned mismatched id")
        return descriptor

    def render(self, request: ReportRequest, manifest: Mapping[str, Any]) -> ReportResult:
        entry = self._entry_for(request.report_id)
        adapter = entry.adapter
        if not hasattr(adapter, 'render'):
            raise ReportError(f"report {request.report_id!r} does not implement render")
        context = self._context(request.report_id, entry, manifest=_freeze_value(manifest))
        try:
            result = adapter.render(request, context)
        except Exception as err:
            raise ReportError(_sanitize_report_error(f'plugin report render failed: {err}')) from err
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
        return ReportContext(
            owner=CapabilityOwner(entry.plugin_id) if entry.plugin_id is not None else None,
            capability_id=report_id,
            manifest=manifest,
        )


def read_report_manifest(path: Path) -> Mapping[str, Any]:
    with Path(path).open('r', encoding='utf-8') as file:
        data = json.load(file)
    manifest = Manifest.from_dict(data)
    return manifest.to_dict()


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
    filename = _report_filename(result.report_id, descriptor.file_extension)
    destination = destination_dir / filename
    if not _is_relative_to(destination.resolve().parent, root):
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
        return True
    except ValueError:
        return False


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    return value


def _sanitize_report_error(message: str) -> str:
    return str(redact_secrets(message))


__all__ = [
    'ReportRegistry',
    'RegisteredReportCapability',
    'export_report_result',
    'read_report_manifest',
]
