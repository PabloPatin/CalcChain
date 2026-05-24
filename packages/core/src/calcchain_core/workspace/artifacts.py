from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..common.hash import sha256_file
from ..io.ref import ExternalRef
from ..utils.validation import mapping_value, optional_list, required_sha256


@dataclass(frozen=True)
class ArtifactRef:
    sha256: str
    sources: list[ExternalRef] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        return cls(
            sha256=required_sha256(data, 'sha256'),
            sources=[
                ExternalRef.from_dict(dict(mapping_value(item, f'sources[{index}]')))
                for index, item in enumerate(optional_list(data, 'sources'), start=1)
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'sha256': self.sha256,
            'sources': [source.to_dict() for source in self.sources],
        }


def artifact_ref(path: Path, sources: list[ExternalRef] | None = None) -> ArtifactRef:
    return ArtifactRef(
        sha256=sha256_file(Path(path)),
        sources=[local_ref(Path(path)), *(sources or [])],
    )


def local_ref(path: Path) -> ExternalRef:
    return ExternalRef.from_dict({'type': 'local', 'path': str(Path(path))})
