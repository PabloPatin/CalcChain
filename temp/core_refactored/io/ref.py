from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RefCredentials:
    public: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None):
        if data is None:
            return None
        return cls(
            public=dict(data.get('public', {})),
            secrets=dict(data.get('secrets', {})),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.public:
            result['public'] = dict(self.public)
        if self.secrets:
            result['secrets'] = dict(self.secrets)
        return result


@dataclass(frozen=True)
class ExternalRef:
    data: dict[str, Any] = field(default_factory=dict)
    credentials: RefCredentials | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        ref_data = dict(data)
        credentials = RefCredentials.from_dict(ref_data.pop('credentials', None))
        return cls(data=ref_data, credentials=credentials)

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.data)
        if self.credentials is not None:
            result['credentials'] = self.credentials.to_dict()
        return result
