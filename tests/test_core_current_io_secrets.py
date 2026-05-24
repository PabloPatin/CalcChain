import unittest

from calcchain_core.capabilities import CapabilityKey, CapabilityOwner, CapabilityRecord, RuntimeCapabilities
from calcchain_core.common.errors import SourceError
from calcchain_core.io import SourceRef, SourceRegistry, TargetRef, TargetRegistry
from calcchain_core.io.ref import RefCredentials
from calcchain_core.secrets import MemorySecretStore, RuntimeSecretsResolver, SecretPersistencePolicy


class MemorySecretsAdapter:
    def __init__(self, values):
        self.values = dict(values)
        self.calls = []

    def can_resolve(self, key, context):
        self.calls.append(('can_resolve', key, dict(context.request_context)))
        return key in self.values

    def resolve(self, key, context):
        self.calls.append(('resolve', key, dict(context.request_context)))
        return self.values[key]


class CapturingSourceAdapter:
    def __init__(self):
        self.contexts = []

    def validate_config(self, ref, context):
        self.contexts.append(context)

    def resolve_lock_ref(self, ref, context):
        return dict(ref)

    def validate_lock_ref(self, ref, context):
        pass

    def list_files(self, ref, context):
        return ['input.txt']

    def read_file(self, ref, relative_path, context):
        return b'data'

    def is_versionable(self, ref, context):
        return False


class SecretLeakingSourceAdapter(CapturingSourceAdapter):
    def validate_config(self, ref, context):
        secret = context.credentials.secrets['password']
        raise RuntimeError(f'failed with {secret}')


class CapturingTargetAdapter:
    def __init__(self):
        self.contexts = []

    def validate_config(self, ref, context):
        self.contexts.append(context)

    def resolve_lock_ref(self, ref, context):
        return dict(ref)

    def validate_lock_ref(self, ref, context):
        pass

    def ensure_root(self, ref, context):
        return dict(ref)

    def write_file(self, ref, relative_path, data, context):
        return {'source': {'type': 'local', 'path': ref['path']}, 'relative_path': relative_path}

    def is_versionable(self, ref, context):
        return False


class TestCoreCurrentIoSecrets(unittest.TestCase):
    def test_runtime_secrets_resolver_uses_memory_policy_without_persistent_store(self):
        adapter = MemorySecretsAdapter({'token-key': 'token-value'})
        runtime = _runtime(CapabilityKey('secrets', 'memory'), adapter)

        class ForbiddenStore:
            def get(self, key):
                raise AssertionError('persistent store must not be read')

            def set(self, key, value):
                raise AssertionError('persistent store must not be written')

        resolver = RuntimeSecretsResolver.from_runtime(
            runtime,
            policy=SecretPersistencePolicy(allow_memory=True, allow_store=False),
            store=ForbiddenStore(),
        )

        self.assertEqual(resolver.resolve('token-key'), 'token-value')
        self.assertEqual(resolver.resolve('token-key'), 'token-value')
        self.assertEqual([call[0] for call in adapter.calls].count('resolve'), 1)

    def test_runtime_secrets_resolver_reads_and_writes_persistent_store(self):
        adapter = MemorySecretsAdapter({'missing-key': 'created-value'})
        store = MemorySecretStore({'stored-key': 'stored-value'})
        resolver = RuntimeSecretsResolver.from_runtime(
            _runtime(CapabilityKey('secrets', 'memory'), adapter),
            policy=SecretPersistencePolicy(allow_memory=True, allow_store=True),
            store=store,
        )

        self.assertEqual(resolver.resolve('stored-key'), 'stored-value')
        self.assertEqual(adapter.calls, [])
        self.assertEqual(resolver.resolve('missing-key'), 'created-value')
        self.assertEqual(store.get('missing-key'), 'created-value')

    def test_source_registry_resolves_credentials_from_secrets_capability(self):
        secrets = MemorySecretsAdapter({'source-password': 'plain-secret'})
        source_adapter = CapturingSourceAdapter()
        runtime = RuntimeCapabilities(
            active_owner_ids=('owner',),
            capabilities={
                CapabilityKey('secrets', 'memory'): CapabilityRecord(
                    CapabilityKey('secrets', 'memory'),
                    secrets,
                    owner=CapabilityOwner('owner'),
                ),
                CapabilityKey('source', 'demo'): CapabilityRecord(
                    CapabilityKey('source', 'demo'),
                    source_adapter,
                    owner=CapabilityOwner('owner'),
                ),
            },
        )
        resolver = RuntimeSecretsResolver.from_runtime(
            runtime,
            policy=SecretPersistencePolicy(allow_memory=False, allow_store=False),
        )
        registry = SourceRegistry.from_runtime(runtime, secrets_resolver=resolver)
        source = SourceRef(
            {'type': 'demo', 'path': 'repo'},
            credentials=RefCredentials(public={'username': 'user'}, secrets={'password': 'source-password'}),
        )

        registry.validate_config(source)

        credentials = source_adapter.contexts[-1].credentials
        self.assertEqual(credentials.public['username'], 'user')
        self.assertEqual(credentials.secrets['password'], 'plain-secret')
        resolve_call = [call for call in secrets.calls if call[0] == 'resolve'][0]
        self.assertEqual(resolve_call[2]['kind'], 'source.credentials')
        self.assertEqual(resolve_call[2]['name'], 'password')
        self.assertEqual(resolve_call[2]['ref'], {'type': 'demo', 'path': 'repo'})

    def test_source_registry_redacts_only_resolved_secret_values(self):
        secret = 'plain-secret'
        runtime = RuntimeCapabilities(
            capabilities={
                CapabilityKey('secrets', 'memory'): CapabilityRecord(
                    CapabilityKey('secrets', 'memory'),
                    MemorySecretsAdapter({'password-key': secret}),
                ),
                CapabilityKey('source', 'leaky'): CapabilityRecord(
                    CapabilityKey('source', 'leaky'),
                    SecretLeakingSourceAdapter(),
                ),
            },
        )
        resolver = RuntimeSecretsResolver.from_runtime(
            runtime,
            policy=SecretPersistencePolicy(allow_memory=False, allow_store=False),
        )
        registry = SourceRegistry.from_runtime(runtime, secrets_resolver=resolver)
        source = SourceRef({'type': 'leaky'}, credentials=RefCredentials(secrets={'password': 'password-key'}))

        with self.assertRaises(SourceError) as caught:
            registry.validate_config(source)

        message = str(caught.exception)
        self.assertNotIn(secret, message)
        self.assertIn('[redacted]', message)

    def test_target_registry_resolves_credentials_and_preserves_them_in_lock_ref(self):
        target_adapter = CapturingTargetAdapter()
        runtime = RuntimeCapabilities(
            capabilities={
                CapabilityKey('secrets', 'memory'): CapabilityRecord(
                    CapabilityKey('secrets', 'memory'),
                    MemorySecretsAdapter({'target-token': 'resolved-token'}),
                ),
                CapabilityKey('target', 'demo'): CapabilityRecord(
                    CapabilityKey('target', 'demo'),
                    target_adapter,
                    owner=CapabilityOwner('target-owner', version='1.2.3'),
                ),
            },
        )
        resolver = RuntimeSecretsResolver.from_runtime(
            runtime,
            policy=SecretPersistencePolicy(allow_memory=False, allow_store=False),
        )
        registry = TargetRegistry.from_runtime(runtime, secrets_resolver=resolver)
        target = TargetRef(
            {'type': 'demo', 'path': 'out'},
            credentials=RefCredentials(secrets={'token': 'target-token'}),
        )

        resolved = registry.resolve_lock_ref(target)
        registry.validate_config(target)

        self.assertEqual(resolved.credentials, target.credentials)
        self.assertEqual(target_adapter.contexts[-1].credentials.secrets['token'], 'resolved-token')
        self.assertEqual(target_adapter.contexts[-1].owner_id, 'target-owner')


def _runtime(key, adapter):
    return RuntimeCapabilities(capabilities={key: CapabilityRecord(key=key, adapter=adapter)})


if __name__ == '__main__':
    unittest.main()
