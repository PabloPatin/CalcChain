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
class RunConfig:
    schema_version: str
    executable: str
    args: list[str] = field(default_factory=list)
    cwd: str = '.'
    timeout_seconds: int | None = None
    encoding: str = 'utf-8'
    stdin_mode: str = 'none'
    stdin_text: str = ''
    env: dict[str, str] = field(default_factory=dict)
    secret_env: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        run = required_mapping(data, 'run')
        if 'output_rule_set' in data or 'output_rule_set' in run:
            raise ConfigFormatError('run.toml must not define output_rule_set')
        if 'env' in run:
            raise ConfigFormatError('env must be a top-level table')
        if 'secret_env' in run:
            raise ConfigFormatError('secret_env must be a top-level list of names')

        timeout = run.get('timeout_seconds')
        if timeout is not None and not isinstance(timeout, int):
            raise ConfigFormatError('timeout_seconds must be an integer or null')

        stdin_mode = optional_str(run, 'stdin_mode') or 'none'
        if stdin_mode not in {'none', 'script', 'manual'}:
            raise ConfigFormatError('stdin_mode must be none, script, or manual')

        return cls(
            schema_version=optional_str(data, 'schema_version') or RUN_CONFIG_SCHEMA_VERSION,
            executable=required_str(run, 'executable'),
            args=[string_value(item, 'args item') for item in optional_list(run, 'args')],
            cwd=optional_str(run, 'cwd') or '.',
            timeout_seconds=timeout,
            encoding=optional_str(run, 'encoding') or 'utf-8',
            stdin_mode=stdin_mode,
            stdin_text=optional_str(run, 'stdin_text') or '',
            env=string_mapping(optional_mapping(data, 'env') or {}),
            secret_env=[string_value(item, 'secret_env item') for item in optional_list(data, 'secret_env')],
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
        result: dict[str, Any] = {'schema_version': self.schema_version, 'run': run}
        if self.env:
            result['env'] = dict(self.env)
        if self.secret_env:
            result['secret_env'] = list(self.secret_env)
        return result
