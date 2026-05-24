from dataclasses import fields
import inspect
import unittest

from calcchain_core.io.auth import AuthError, AuthService
from calcchain_plugin_system import (
    PLUGIN_API_VERSION,
    PLUGIN_DIAGNOSTIC_PHASES,
    AuthAdapter,
    AuthContext,
    AuthCredentials,
    AuthField,
    AuthRegistrar,
    AuthRequirement,
    CapabilityKey,
    CapabilityRecord,
    CalcChainPlugin,
    CapabilityRegistrar,
    PluginCapabilityConflictError,
    PluginContext,
    PluginDiagnostic,
    PluginEntrypointError,
    PluginError,
    PluginRefMetadata,
    PluginRegistrationError,
    PublishedRef,
    ReportAdapter,
    ReportContext,
    ReportDescriptor,
    ReportRegistrar,
    ReportRequest,
    ReportResult,
    SourceAdapter,
    SourceContext,
    SourceRegistrar,
    TargetAdapter,
    TargetContext,
    TargetRegistrar,
    create_plugin_context,
    redact_secrets,
)
from calcchain_plugin_system import PluginRuntimeSet


class DummyPlugin:
    plugin_id = 'example.plugin'
    plugin_version = '1.0.0'

    def register(self, context: PluginContext) -> None:
        context.sources.register('git', object(), owner=self.plugin_id)
        context.reports.register('summary', object(), owner=self.plugin_id)


class TestCorePluginApi(unittest.TestCase):
    def test_public_import_path_exports_stage_one_contract(self):
        self.assertEqual(PLUGIN_API_VERSION, '1.0')
        self.assertTrue(issubclass(PluginError, Exception))
        self.assertEqual(
            PLUGIN_DIAGNOSTIC_PHASES,
            (
                'discovery',
                'metadata_read',
                'metadata_validation',
                'compatibility_check',
                'dependency_plan',
                'dependency_install',
                'entrypoint_import',
                'plugin_instantiate',
                'capability_registration',
                'activation_commit',
            ),
        )
        self.assertEqual(
            [field.name for field in fields(PluginContext)],
            ['sources', 'targets', 'reports', 'auth'],
        )

    def test_runtime_contexts_and_value_objects_are_public(self):
        self.assertEqual(
            [field.name for field in fields(SourceContext)],
            ['owner_id', 'capability_id', 'auth', 'logger'],
        )
        self.assertEqual(
            [field.name for field in fields(TargetContext)],
            ['owner_id', 'capability_id', 'auth', 'logger'],
        )
        self.assertEqual(
            [field.name for field in fields(AuthContext)],
            ['owner_id', 'capability_id', 'logger'],
        )
        self.assertEqual(
            [field.name for field in fields(ReportContext)],
            ['owner_id', 'capability_id', 'manifest', 'logger'],
        )

        metadata = PluginRefMetadata.from_dict({'id': 'plugin.one', 'version': '1.2.3'})
        self.assertEqual(metadata.to_dict(), {'id': 'plugin.one', 'version': '1.2.3'})
        self.assertEqual(PublishedRef({'type': 'git'}).ref['type'], 'git')
        self.assertEqual(ReportDescriptor('summary', 'Summary', 'text/html', '.html').title, 'Summary')
        self.assertEqual(ReportRequest('summary', parameters={'format': 'html'}).parameters['format'], 'html')
        self.assertEqual(ReportResult('summary', b'ok', 'text/plain').content, b'ok')
        requirement = AuthRequirement(
            scheme='username_password',
            scope={'location': 'https://svn.example.org/repo'},
            fields=(AuthField('username', False), AuthField('password', True)),
            persistence='forbidden',
        )
        self.assertEqual(requirement.scheme, 'username_password')
        self.assertEqual(requirement.scope['location'], 'https://svn.example.org/repo')
        self.assertEqual(requirement.fields[1].name, 'password')
        self.assertTrue(requirement.fields[1].secret)
        self.assertFalse(requirement.optional)

        mapped_requirement = AuthRequirement(
            scheme='token',
            fields=({'name': 'token', 'secret': True},),
            optional=True,
        )
        self.assertEqual(mapped_requirement.fields, (AuthField('token', True),))
        self.assertTrue(mapped_requirement.optional)
        with self.assertRaises(ValueError):
            AuthField('', True)
        with self.assertRaises(ValueError):
            AuthField('token', 'yes')

    def test_auth_credentials_repr_redacts_runtime_values(self):
        credentials = AuthCredentials({'token': 'plain-secret-value'})

        self.assertEqual(repr(credentials), 'AuthCredentials([redacted])')
        self.assertEqual(str(credentials), 'AuthCredentials([redacted])')
        self.assertNotIn('plain-secret-value', repr(credentials))
        self.assertFalse(hasattr(credentials, 'to_dict'))

    def test_auth_service_selects_runtime_provider_and_session_caches_credentials(self):
        class AuthProvider:
            def __init__(self):
                self.calls = []

            def can_handle(self, requirement, context):
                self.calls.append(('can_handle', requirement.scheme))
                return requirement.scheme == 'token'

            def validate_requirement(self, requirement, context):
                self.calls.append(('validate_requirement', requirement.scope['repo']))

            def get_credentials(self, requirement, context):
                self.calls.append(('get_credentials', requirement.scope['repo']))
                return AuthCredentials({'token': 'secret-token'})

        provider = AuthProvider()
        runtime = PluginRuntimeSet(
            active_owner_ids=('plugin.auth',),
            environment=object(),
            capabilities={
                CapabilityKey('auth', 'pat'): CapabilityRecord(
                    key=CapabilityKey('auth', 'pat'),
                    capability=provider,
                    owner='plugin.auth',
                ),
            },
        )
        service = AuthService.from_runtime(runtime)
        requirement = AuthRequirement(
            scheme='token',
            scope={'repo': 'repo'},
            fields=(AuthField('token', True),),
            persistence='forbidden',
        )

        first = service.get_credentials(requirement)
        second = service.get_credentials(requirement)

        self.assertIs(first, second)
        self.assertTrue(service.has_provider(requirement))
        self.assertEqual(
            provider.calls,
            [
                ('can_handle', 'token'),
                ('validate_requirement', 'repo'),
                ('get_credentials', 'repo'),
                ('can_handle', 'token'),
            ],
        )

    def test_auth_service_ignores_persistence_when_policy_disables_storage_and_redacts_fields(self):
        class AuthProvider:
            def can_handle(self, requirement, context):
                return requirement.scheme == 'token'

            def validate_requirement(self, requirement, context):
                pass

            def get_credentials(self, requirement, context):
                return AuthCredentials({'token': 'secret-token'})

        class FailingAuthProvider:
            def can_handle(self, requirement, context):
                return True

            def validate_requirement(self, requirement, context):
                raise RuntimeError("invalid {'password': 'plain-secret-value'}")

            def get_credentials(self, requirement, context):
                raise AssertionError('must not be called')

        runtime = PluginRuntimeSet(
            active_owner_ids=('plugin.auth', 'plugin.failing'),
            environment=object(),
            capabilities={
                CapabilityKey('auth', 'token'): CapabilityRecord(
                    key=CapabilityKey('auth', 'token'),
                    capability=AuthProvider(),
                    owner='plugin.auth',
                ),
                CapabilityKey('auth', 'failing'): CapabilityRecord(
                    key=CapabilityKey('auth', 'failing'),
                    capability=FailingAuthProvider(),
                    owner='plugin.failing',
                ),
            },
        )
        service = AuthService.from_runtime(runtime)

        credentials = service.get_credentials(
            AuthRequirement(
                scheme='token',
                fields=(AuthField('token', True),),
                persistence='allowed',
            )
        )

        self.assertEqual(credentials.values['token'], 'secret-token')

        with self.assertRaises(AuthError) as provider_caught:
            service.get_credentials(
                AuthRequirement(
                    scheme='username_password',
                    fields=(AuthField('username', False), AuthField('password', True)),
                    persistence='forbidden',
                ),
            )

        provider_message = str(provider_caught.exception)
        self.assertIn("'password': '[redacted]'", provider_message)
        self.assertNotIn('plain-secret-value', provider_message)

    def test_runtime_protocols_expose_expected_signatures(self):
        expected = {
            SourceAdapter.validate_config: ['self', 'ref', 'context'],
            SourceAdapter.resolve_lock_ref: ['self', 'ref', 'context'],
            SourceAdapter.validate_lock_ref: ['self', 'lock_ref', 'context'],
            SourceAdapter.list_files: ['self', 'ref', 'context'],
            SourceAdapter.read_file: ['self', 'ref', 'relative_path', 'context'],
            SourceAdapter.is_versionable: ['self', 'ref', 'context'],
            TargetAdapter.validate_config: ['self', 'ref', 'context'],
            TargetAdapter.resolve_lock_ref: ['self', 'ref', 'context'],
            TargetAdapter.validate_lock_ref: ['self', 'lock_ref', 'context'],
            TargetAdapter.ensure_root: ['self', 'ref', 'context'],
            TargetAdapter.write_file: ['self', 'ref', 'relative_path', 'data', 'context'],
            TargetAdapter.is_versionable: ['self', 'ref', 'context'],
            AuthAdapter.can_handle: ['self', 'requirement', 'context'],
            AuthAdapter.validate_requirement: ['self', 'requirement', 'context'],
            AuthAdapter.get_credentials: ['self', 'requirement', 'context'],
            ReportAdapter.describe: ['self', 'context'],
            ReportAdapter.render: ['self', 'request', 'context'],
        }

        for method, parameters in expected.items():
            with self.subTest(method=method.__qualname__):
                self.assertEqual(list(inspect.signature(method).parameters), parameters)

    def test_registrar_interfaces_expose_stage_one_register_signature(self):
        for registrar_type in (
            CapabilityRegistrar,
            SourceRegistrar,
            TargetRegistrar,
            ReportRegistrar,
            AuthRegistrar,
        ):
            with self.subTest(registrar_type=registrar_type.__name__):
                signature = inspect.signature(registrar_type.register)
                self.assertEqual(list(signature.parameters), ['self', 'id', 'capability', 'owner'])
                self.assertEqual(signature.parameters['id'].annotation, str)
                self.assertEqual(signature.parameters['capability'].annotation, object)
                self.assertIs(
                    signature.parameters['owner'].kind,
                    inspect.Parameter.KEYWORD_ONLY,
                )
                self.assertEqual(signature.parameters['owner'].annotation, str)

    def test_plugin_protocol_and_limited_context_register_capabilities(self):
        context, registry = create_plugin_context(owner='example.plugin')
        plugin: CalcChainPlugin = DummyPlugin()

        plugin.register(context)

        snapshot = registry.snapshot()
        self.assertEqual(
            sorted(key.qualified_id for key in snapshot),
            ['report:summary', 'source:git'],
        )
        self.assertEqual(snapshot[CapabilityKey('source', 'git')].owner, 'example.plugin')
        self.assertFalse(hasattr(context, 'manager'))

    def test_duplicate_namespace_and_id_raises_conflict(self):
        context, registry = create_plugin_context(owner='plugin.one')
        context.sources.register('git', object(), owner='plugin.one')

        with self.assertRaises(PluginCapabilityConflictError) as caught:
            context.sources.register('git', object(), owner='plugin.one')

        self.assertEqual(caught.exception.diagnostic.phase, 'capability_registration')
        self.assertEqual(caught.exception.diagnostic.safe_details['existing_owner'], 'plugin.one')
        self.assertEqual(len(registry.snapshot()), 1)

    def test_same_id_in_different_namespaces_is_allowed(self):
        context, registry = create_plugin_context(owner='plugin.one')

        context.sources.register('git', object(), owner='plugin.one')
        context.targets.register('git', object(), owner='plugin.one')

        self.assertEqual(
            sorted(key.qualified_id for key in registry.snapshot()),
            ['source:git', 'target:git'],
        )

    def test_owner_mismatch_raises_registration_error(self):
        context, registry = create_plugin_context(owner='plugin.one')

        with self.assertRaises(PluginRegistrationError) as caught:
            context.auth.register('token', object(), owner='plugin.two')

        self.assertEqual(caught.exception.diagnostic.safe_details['expected_owner'], 'plugin.one')
        self.assertEqual(registry.snapshot(), {})

    def test_one_plugin_can_register_multiple_capabilities(self):
        context, registry = create_plugin_context(owner='plugin.one')

        context.sources.register('git', object(), owner='plugin.one')
        context.sources.register('svn', object(), owner='plugin.one')
        context.targets.register('release', object(), owner='plugin.one')
        context.reports.register('html', object(), owner='plugin.one')
        context.auth.register('pat', object(), owner='plugin.one')

        self.assertEqual(len(registry.snapshot()), 5)

    def test_registry_snapshot_is_immutable(self):
        context, registry = create_plugin_context(owner='plugin.one')
        context.sources.register('git', object(), owner='plugin.one')
        snapshot = registry.snapshot()

        with self.assertRaises(TypeError):
            snapshot[CapabilityKey('source', 'other')] = object()

    def test_redaction_masks_known_secret_values_and_common_credentials(self):
        secret = 'plain-secret-value'
        diagnostic = PluginDiagnostic.create(
            plugin_id='plugin.one',
            phase='metadata_validation',
            code='invalid_metadata',
            message='Cannot read token=abc123 or use plain-secret-value',
            safe_details={
                'url': 'https://user:password@example.org/repo',
                'headers': ['Authorization: Bearer raw-access-token'],
                'nested': {'api_key': 'plain-secret-value'},
            },
            secret_values=[secret],
        )

        self.assertNotIn('abc123', diagnostic.message)
        self.assertNotIn(secret, diagnostic.message)
        self.assertEqual(diagnostic.plugin_id, 'plugin.one')
        self.assertEqual(diagnostic.phase, 'metadata_validation')
        self.assertEqual(diagnostic.code, 'invalid_metadata')
        self.assertEqual(diagnostic.message, 'Cannot read token=[secret] or use [secret]')
        self.assertIn('token=[secret]', diagnostic.message)
        self.assertEqual(diagnostic.safe_details['url'], 'https://[redacted]@example.org/repo')
        self.assertEqual(diagnostic.safe_details['headers'], ('Authorization: Bearer [secret]',))
        self.assertEqual(diagnostic.safe_details['nested']['api_key'], '[secret]')

        redacted = redact_secrets('password=hunter2 access_token=top-secret')
        self.assertNotIn('hunter2', redacted)
        self.assertNotIn('top-secret', redacted)

    def test_public_error_message_is_redacted_and_cause_stays_internal(self):
        cause = RuntimeError('low-level plain-secret-value')

        try:
            raise PluginEntrypointError(
                'Entrypoint failed with token=abc123',
                plugin_id='plugin.one',
                secret_values=['plain-secret-value'],
            ) from cause
        except PluginEntrypointError as error:
            caught = error

        self.assertIs(caught.__cause__, cause)
        self.assertNotIn('abc123', str(caught))
        self.assertNotIn('plain-secret-value', str(caught))
        self.assertEqual(caught.diagnostic.phase, 'entrypoint_import')


if __name__ == '__main__':
    unittest.main()
