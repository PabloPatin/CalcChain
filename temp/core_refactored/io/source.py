from .ref import ExternalRef, RefCredentials


SourceCredentials = RefCredentials
SourceRef = ExternalRef


class SourceRegistry:
    def __init__(self, runtime=None, *, auth=None):
        self.runtime = runtime
        self.auth = auth

    @classmethod
    def from_runtime(cls, runtime=None, *, auth=None):
        return cls(runtime, auth=auth)

    def validate_config(self, source: SourceRef) -> None:
        return None

    def resolve_lock_ref(self, source: SourceRef) -> SourceRef:
        return source

    def validate_lock_ref(self, source: SourceRef) -> None:
        return None

    def list_files(self, source: SourceRef) -> list[str]:
        raise NotImplementedError('SourceRegistry.list_files is not configured')

    def read_file(self, source: SourceRef, path: str) -> bytes:
        raise NotImplementedError('SourceRegistry.read_file is not configured')
