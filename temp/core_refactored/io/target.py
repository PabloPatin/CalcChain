from .ref import ExternalRef, RefCredentials


TargetCredentials = RefCredentials
TargetRef = ExternalRef


class TargetRegistry:
    def __init__(self, runtime=None, *, secrets_resolver=None):
        self.runtime = runtime
        self.secrets_resolver = secrets_resolver

    @classmethod
    def from_runtime(cls, runtime=None, *, secrets_resolver=None):
        return cls(runtime, secrets_resolver=secrets_resolver)
