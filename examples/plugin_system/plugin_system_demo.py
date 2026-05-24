from __future__ import annotations

import tempfile
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from calcchain_core import CalculationCore  # noqa: E402
from calcchain_plugin_system import activate_plugins  # noqa: E402
from calcchain_plugin_system.errors import PluginError  # noqa: E402


PLUGIN_ROOTS = (REPO_ROOT / 'plugins',)
PLUGIN_SETTINGS = REPO_ROOT / 'plugins.json'
PLUGIN_ENVS = REPO_ROOT / 'plugin_envs'


def main() -> int:
    print('CalcChain explicit plugin bootstrap demo')
    print(f'plugin roots: {PLUGIN_ROOTS}')
    print(f'settings: {PLUGIN_SETTINGS}')

    try:
        runtime_set = activate_plugins(
            PLUGIN_ROOTS,
            PLUGIN_SETTINGS,
            PLUGIN_ENVS,
        )
    except PluginError as exc:
        print_plugin_error(exc)
        return 2

    print(f'active plugin ids: {runtime_set.active_owner_ids}')
    print('runtime capabilities:')
    for key, record in sorted(runtime_set.capabilities.items(), key=lambda item: item[0].qualified_id):
        print(f'  - {key.qualified_id} owner={record.owner}')

    with tempfile.TemporaryDirectory() as tmp:
        job_dir = Path(tmp) / 'job'
        core = CalculationCore(job_dir, runtime=runtime_set)
        print()
        print('CalculationCore constructed with explicit PluginRuntimeSet')
        print(f'source types: {sorted(core.source_registry._entries)}')
        print(f'target types: {sorted(core.target_registry._entries)}')
        print('No SVN network operation is run by this demo.')

    return 0


def print_plugin_error(exc: PluginError) -> None:
    diagnostic = exc.diagnostic
    print()
    print('Plugin error:')
    print(f'  code: {diagnostic.code}')
    print(f'  phase: {diagnostic.phase}')
    print(f'  plugin_id: {diagnostic.plugin_id}')
    print(f'  message: {diagnostic.message}')
    print(f'  details: {diagnostic.safe_details}')


if __name__ == '__main__':
    raise SystemExit(main())
