from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..common.errors import ConfigFormatError
from ..config import RUN_CONFIG_SCHEMA_VERSION
from ..utils.validation import (
    optional_list,
    optional_mapping,
    optional_str,
    required_mapping,
    required_str,
    string_mapping,
    string_value,
)


@dataclass(frozen=True)
class RunEnvironment:
    public: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None):
        if data is None:
            return cls()
        return cls(
            public=string_mapping(optional_mapping(data, 'public') or {}),
            secrets=string_mapping(optional_mapping(data, 'secrets') or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.public:
            result['public'] = dict(self.public)
        if self.secrets:
            result['secrets'] = dict(self.secrets)
        return result


@dataclass(frozen=True)
class RunConfig:
    schema_version: str
    executable: str
    args: list[str] = field(default_factory=list)
    cwd: str = '.'
    timeout_seconds: int | None = None
    encoding: str = 'utf-8'
    stdin_mode: str = 'none'
    stdin_text: str = ''
    env: RunEnvironment = field(default_factory=RunEnvironment)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        run = required_mapping(data, 'run')

        timeout = run.get('timeout_seconds')
        if timeout is not None and not isinstance(timeout, int):
            raise ConfigFormatError('timeout_seconds must be an integer or null')

        stdin_mode = optional_str(run, 'stdin_mode') or 'none'
        if stdin_mode not in {'none', 'script'}:
            raise ConfigFormatError('stdin_mode must be none or script')

        return cls(
            schema_version=optional_str(data, 'schema_version') or RUN_CONFIG_SCHEMA_VERSION,
            executable=required_str(run, 'executable'),
            args=[string_value(item, 'args item') for item in optional_list(run, 'args')],
            cwd=optional_str(run, 'cwd') or '.',
            timeout_seconds=timeout,
            encoding=optional_str(run, 'encoding') or 'utf-8',
            stdin_mode=stdin_mode,
            stdin_text=optional_str(run, 'stdin_text') or '',
            env=RunEnvironment.from_dict(optional_mapping(run, 'env')),
        )

    def to_dict(self) -> dict[str, Any]:
        run: dict[str, Any] = {
            'executable': self.executable,
            'args': list(self.args),
            'cwd': self.cwd,
            'timeout_seconds': self.timeout_seconds,
            'encoding': self.encoding,
            'stdin_mode': self.stdin_mode,
            'stdin_text': self.stdin_text,
        }
        env = self.env.to_dict()
        if env:
            run['env'] = env
        return {'schema_version': self.schema_version, 'run': run}
