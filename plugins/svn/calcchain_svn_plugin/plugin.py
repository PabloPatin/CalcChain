from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Mapping
from urllib.parse import urlsplit

from calcchain_plugin_system import PluginContext
from svn_client.client import SvnClient

PLUGIN_ID = 'calcchain.svn'
PLUGIN_VERSION = '0.1.0'


class SvnSourceAdapter:
    plugin_version = PLUGIN_VERSION

    def __init__(self, client_factory=None):
        self._client_factory = client_factory or _default_client_factory

    def validate_config(self, ref: Mapping[str, Any], context) -> None:
        _validate_svn_ref(ref, field='source', require_concrete_revision=False)

    def resolve_lock_ref(self, ref: Mapping[str, Any], context) -> dict[str, Any]:
        self.validate_config(ref, context)
        revision = ref.get('revision')
        try:
            info = self._client(ref, context).info(ref['path'], revision=revision)
        except Exception as err:
            raise RuntimeError(_sanitize_svn_error(f'svn info failed: {err}', ref)) from err
        if revision == 'HEAD' or revision is None:
            revision = info.commit_revision
        elif isinstance(revision, str):
            revision = int(revision)
        return _safe_lock_ref(ref, revision=revision)

    def validate_lock_ref(self, lock_ref: Mapping[str, Any], context) -> None:
        _validate_svn_ref(lock_ref, field='source', require_concrete_revision=True)

    def list_files(self, ref: Mapping[str, Any], context) -> list[str]:
        self.validate_lock_ref(ref, context)
        try:
            tree = self._client(ref, context).list(ref['path'], recursive=True, revision=ref.get('revision'))
        except Exception as err:
            raise RuntimeError(_sanitize_svn_error(f'svn list failed: {err}', ref)) from err
        return sorted(
            _normalize_relative_path(node.rel_path, field='svn source file')
            for node in tree.nodes
            if node.kind == 'file'
        )

    def read_file(self, ref: Mapping[str, Any], relative_path: str, context) -> bytes:
        self.validate_lock_ref(ref, context)
        safe_path = _normalize_relative_path(relative_path, field='svn source file')
        source_path = _join_ref_path(ref['path'], safe_path)
        try:
            data = self._client(ref, context).cat(source_path, revision=ref.get('revision'), return_binary=True)
        except Exception as err:
            raise RuntimeError(_sanitize_svn_error(f'svn cat failed: {err}', ref)) from err
        if not isinstance(data, bytes):
            raise RuntimeError(f'svn cat returned text for file: {relative_path}')
        return data

    def is_versionable(self, ref: Mapping[str, Any], context) -> bool:
        self.validate_lock_ref(ref, context)
        return True

    def _client(self, ref: Mapping[str, Any], context):
        credentials = _credentials_for(ref, context, kind='source')
        if credentials is None:
            return self._client_factory(ref['location'])
        return self._client_factory(
            ref['location'],
            username=credentials.get('username'),
            password=credentials.get('password'),
        )


class SvnTargetAdapter:
    plugin_version = PLUGIN_VERSION

    def __init__(self, client_factory=None):
        self._client_factory = client_factory or _default_client_factory

    def validate_config(self, ref: Mapping[str, Any], context) -> None:
        _validate_svn_ref(ref, field='target', require_concrete_revision=False)

    def resolve_lock_ref(self, ref: Mapping[str, Any], context) -> dict[str, Any]:
        self.validate_config(ref, context)
        try:
            info = self._client(ref, context).info(ref['path'], revision=ref.get('revision'))
        except Exception as err:
            raise RuntimeError(_sanitize_svn_error(f'svn info failed: {err}', ref)) from err
        return _safe_lock_ref(ref, revision=info.commit_revision)

    def validate_lock_ref(self, lock_ref: Mapping[str, Any], context) -> None:
        _validate_svn_ref(lock_ref, field='target', require_concrete_revision=True)

    def ensure_root(self, ref: Mapping[str, Any], context) -> dict[str, Any]:
        self.validate_lock_ref(ref, context)
        try:
            self._client(ref, context).mkdir(ref['path'], message='', parents=True, exist_ok=True)
        except Exception as err:
            raise RuntimeError(_sanitize_svn_error(f'svn mkdir failed: {err}', ref)) from err
        return dict(ref)

    def write_file(self, ref: Mapping[str, Any], relative_path: str, data: bytes, context) -> Mapping[str, Any]:
        self.validate_lock_ref(ref, context)
        safe_path = _normalize_relative_path(relative_path, field='svn target file')
        target_path = _join_ref_path(ref['path'], safe_path)
        try:
            with tempfile.NamedTemporaryFile(delete=False) as file:
                file.write(data)
                tmp_path = Path(file.name)
            try:
                self._client(ref, context).import_(tmp_path, target_path, message='', force=True)
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as err:
            raise RuntimeError(_sanitize_svn_error(f'svn import failed: {err}', ref)) from err
        return {
            'source': {
                'type': 'svn',
                'location': ref['location'],
                'path': target_path,
                'revision': ref['revision'],
            },
            'relative_path': safe_path,
        }

    def is_versionable(self, ref: Mapping[str, Any], context) -> bool:
        self.validate_lock_ref(ref, context)
        return True

    def _client(self, ref: Mapping[str, Any], context):
        credentials = _credentials_for(ref, context, kind='target')
        if credentials is None:
            return self._client_factory(ref['location'])
        return self._client_factory(
            ref['location'],
            username=credentials.get('username'),
            password=credentials.get('password'),
        )


class SvnPlugin:
    plugin_id = PLUGIN_ID
    plugin_version = PLUGIN_VERSION

    def register(self, context: PluginContext) -> None:
        context.sources.register('svn', SvnSourceAdapter(), owner=self.plugin_id)
        context.targets.register('svn', SvnTargetAdapter(), owner=self.plugin_id)


def _credentials_for(ref: Mapping[str, Any], context, *, kind: str):
    credentials = getattr(context, 'credentials', None)
    if credentials is None:
        return None
    public = getattr(credentials, 'public', {})
    secrets = getattr(credentials, 'secrets', {})
    username = public.get('username') or secrets.get('username')
    password = secrets.get('password') or public.get('password')
    if username is None and password is None:
        return None
    return {'username': username, 'password': password}


def _validate_svn_ref(ref: Mapping[str, Any], *, field: str, require_concrete_revision: bool) -> None:
    if ref.get('type') != 'svn':
        raise RuntimeError(f'expected svn {field}, got {ref.get("type")}')
    location = ref.get('location')
    if not isinstance(location, str) or not location:
        raise RuntimeError(f'svn {field} requires location')
    if '@' in urlsplit(location).netloc:
        raise RuntimeError(f'svn {field} location must not contain userinfo')
    path = ref.get('path')
    if not isinstance(path, str) or not path:
        raise RuntimeError(f'svn {field} requires path')
    _normalize_relative_path(path, field=f'svn {field} path')
    revision = ref.get('revision')
    if require_concrete_revision:
        if isinstance(revision, int) and revision >= 0:
            return
        if isinstance(revision, str) and revision.isdecimal():
            return
        raise RuntimeError(f'resolved svn {field} revision must be concrete')
    if revision is None or revision == 'HEAD':
        return
    if isinstance(revision, int) and revision >= 0:
        return
    if isinstance(revision, str) and revision.isdecimal():
        return
    raise RuntimeError(f'svn {field} revision must be HEAD or a concrete revision')


def _safe_lock_ref(ref: Mapping[str, Any], *, revision: int | str) -> dict[str, Any]:
    lock_ref = {
        'type': 'svn',
        'location': ref['location'],
        'path': ref['path'],
        'revision': revision,
    }
    return lock_ref


def _default_client_factory(location: str, *, username: str | None = None, password: str | None = None) -> SvnClient:
    return SvnClient(location, username=username, password=password, check_exists=False)


def _sanitize_svn_error(message: str, ref: Mapping[str, Any]) -> str:
    location = ref.get('location')
    if isinstance(location, str):
        message = message.replace(location, _redact_location(location))
    return message


def _redact_location(location: str) -> str:
    parsed = urlsplit(location)
    if '@' not in parsed.netloc:
        return location
    host = parsed.netloc.rsplit('@', maxsplit=1)[-1]
    return f'{parsed.scheme}://[redacted]@{host}{parsed.path}'


def _join_ref_path(base_path: str, relative_path: str) -> str:
    base = base_path.replace('\\', '/').strip('/')
    if not base:
        return relative_path
    return f'{base}/{relative_path}'


def _normalize_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise RuntimeError(f'{field} must be relative: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts:
        raise RuntimeError(f'{field} must not contain path traversal: {value}')
    result = path.as_posix()
    if result in {'', '.'}:
        raise RuntimeError(f'{field} must identify a file: {value}')
    return result


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()
