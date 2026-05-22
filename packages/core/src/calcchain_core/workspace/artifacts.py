from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from calcchain_core.common.errors import ConfigFormatError
from calcchain_core.common.hash import sha256_file
from calcchain_core.models import ArtifactRef, SourceRef, SourceType, TargetRef


def artifact_ref(path: Path, published_sources: list[SourceRef] = []) -> ArtifactRef:
    return ArtifactRef(
        sha256=sha256_file(Path(path)),
        sources=[local_source(Path(path)), *published_sources],
    )


def local_source(path: Path) -> SourceRef:
    return SourceRef(type=SourceType.LOCAL, path=str(Path(path)))


def published_source(target: TargetRef, relative_path: str) -> SourceRef:
    safe_relative_path = _safe_relative_path(relative_path)
    if _type_id(target.type) == SourceType.LOCAL.value:
        return SourceRef(type=SourceType.LOCAL, path=_join_posix(target.path, safe_relative_path))

    if _type_id(target.type) != SourceType.SVN.value:
        return SourceRef(
            type=target.type,
            location=target.location,
            path=_join_posix(target.path, safe_relative_path),
            revision=target.revision,
            plugin=target.plugin,
            extra=dict(target.extra),
        )

    if target.location is None:
        raise ConfigFormatError('svn published source requires location')
    if '@' in urlsplit(target.location).netloc:
        raise ConfigFormatError('svn published source location must not contain userinfo')
    return SourceRef(
        type=SourceType.SVN,
        location=target.location,
        path=_join_posix(target.path, safe_relative_path),
        revision=target.revision,
    )


def _safe_relative_path(value: str) -> str:
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise ConfigFormatError(f'published source relative path must be relative: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts or path.as_posix() in {'', '.'}:
        raise ConfigFormatError(f'published source relative path is unsafe: {value}')
    return path.as_posix()


def _join_posix(base_path: str, relative_path: str) -> str:
    base = base_path.replace('\\', '/').strip('/')
    if not base:
        return relative_path
    return f'{base}/{relative_path}'


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()


def _type_id(value: SourceType | str) -> str:
    if isinstance(value, SourceType):
        return value.value
    return value
