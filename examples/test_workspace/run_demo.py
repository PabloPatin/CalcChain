from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import tomlkit


WORKSPACE = Path(__file__).resolve().parent
REPO_ROOT = WORKSPACE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from calcchain_core.api import CalculationCore  # noqa: E402
from calcchain_core.models import RuleSetType  # noqa: E402
from calcchain_core.restore.restore import RestoreRequest  # noqa: E402


JOB = WORKSPACE / 'job'
CODE = WORKSPACE / 'sources' / 'code'
INPUT = WORKSPACE / 'sources' / 'input'
PUBLISHED_SERVICE = WORKSPACE / 'published_service'
PUBLISHED_OUTPUTS = WORKSPACE / 'published_outputs'
PUBLISHED_LOGS = WORKSPACE / 'published_logs'
RESTORED = WORKSPACE / 'restored'


def main() -> None:
    reset_runtime()
    write_job_configs()

    core = CalculationCore(JOB)

    input('Далее ->')

    print('1. create_build_lock')
    lock = core.create_build_lock()
    print(f'   build name: {lock.build.name}')

    input('Далее ->')

    print('2. validate_build')
    plan = core.validate_build()
    print(f'   plan entries: {len(plan.entries)}')

    input('Далее ->')

    print('3. build')
    build_result = core.build()
    print(f'   dry_run: {build_result.dry_run}')

    input('Далее ->')

    print('4. simulate manual input change before run')
    work_input = JOB / 'work' / 'input' / 'mesh.txt'
    work_input.write_text('changed mesh\n', encoding='utf-8')
    print(f'   changed: {work_input.relative_to(WORKSPACE).as_posix()}')

    input('Далее ->')

    print('5. run')
    manifest = core.run()
    print(f'   run status: {manifest.to_dict()["run"]["status"]}')

    input('Далее ->')

    print('6. publish dry-run')
    dry_publish = core.publish(dry_run=True)
    print(f'   dry_run: {dry_publish.dry_run}')

    input('Далее ->')

    print('7. publish')
    publish_result = core.publish()
    print(f'   manifest status: {publish_result.updated_manifest.to_dict()["job"]["status"]}')

    input('Далее ->')

    print('8. remove original job-local frozen inputs')
    original_frozen = JOB / '.calcchain' / 'frozen_inputs'
    if original_frozen.exists():
        shutil.rmtree(original_frozen)
    print(f'   exists after delete: {original_frozen.exists()}')

    input('Далее ->')

    published_manifest = PUBLISHED_SERVICE / 'manifest.json'
    print('9. restore dry-run from published manifest')
    dry_restore = core.restore(RestoreRequest(published_manifest, RESTORED, dry_run=True))
    print(f'   status: {dry_restore.status}, files planned: {len(dry_restore.restored_files)}')

    input('Далее ->')

    print('10. restore from published manifest')
    restore_result = core.restore(RestoreRequest(published_manifest, RESTORED))
    restored_value = (RESTORED / 'work' / 'results' / 'value.txt').read_text(encoding='utf-8').strip()
    print(f'   status: {restore_result.status}, restored value: {restored_value}')

    input('Далее ->')

    print('11. cleanup dry-run')
    dry_cleanup = core.cleanup(dry_run=True)
    print(f'   status: {dry_cleanup.status}, planned paths: {dry_cleanup.removed_paths}')

    input('Далее ->')

    print('12. cleanup')
    cleanup = core.cleanup()
    print(f'   status: {cleanup.status}')

    input('Далее ->')

    print_summary()


def reset_runtime() -> None:
    for path in (JOB, PUBLISHED_SERVICE, PUBLISHED_OUTPUTS, PUBLISHED_LOGS, RESTORED):
        if path.exists():
            shutil.rmtree(path)
    JOB.mkdir(parents=True)


def write_job_configs() -> None:
    write_toml(
        JOB / 'build.toml',
        {
            'build': {'name': 'test-workspace-case'},
            'code': {'source': {'type': 'local', 'path': str(CODE)}},
            'inputs': [{'name': 'input', 'source': {'type': 'local', 'path': str(INPUT)}}],
        },
    )
    write_toml(
        JOB / 'run.toml',
        {'run': {'executable': sys.executable, 'args': ['solver.py'], 'cwd': '.', 'timeout_seconds': 10}},
    )
    write_toml(
        JOB / 'publish.toml',
        {
            'publish': {'message': 'test workspace publish'},
            'service_target': {'type': 'local', 'path': str(PUBLISHED_SERVICE)},
            'targets': [
                {
                    'name': 'outputs',
                    'type': 'local',
                    'path': str(PUBLISHED_OUTPUTS),
                    'rule_sets': ['standard_outputs'],
                },
                {
                    'name': 'logs',
                    'type': 'local',
                    'path': str(PUBLISHED_LOGS),
                    'rule_sets': ['standard_logs'],
                },
            ],
        },
    )
    (JOB / 'rules.json').write_text(
        json.dumps(
            {
                'rule_sets': {
                    'standard_outputs': {
                        'type': RuleSetType.OUTPUT.value,
                        'status': 'stable',
                        'ensure_all_files': True,
                        'rules': [{'source': 'results/(.*)', 'destination': '<capt:1>'}],
                    },
                    'standard_logs': {
                        'type': RuleSetType.LOGS.value,
                        'status': 'stable',
                        'ensure_all_files': True,
                        'rules': [{'source': 'logs/(.*)', 'destination': '<capt:1>'}],
                    },
                },
            },
            indent=2,
        ),
        encoding='utf-8',
    )


def write_toml(path: Path, data: dict) -> None:
    path.write_text(tomlkit.dumps(data), encoding='utf-8')


def print_summary() -> None:
    output = PUBLISHED_OUTPUTS / 'value.txt'
    log = PUBLISHED_LOGS / 'solver.log'
    service_manifest = PUBLISHED_SERVICE / 'manifest.json'
    service_frozen = PUBLISHED_SERVICE / 'frozen_inputs' / 'input' / 'mesh.txt'
    restored_output = RESTORED / 'work' / 'results' / 'value.txt'
    print('\nSummary')
    print(f'- published output: {output.relative_to(WORKSPACE).as_posix()} -> {output.read_text(encoding="utf-8").strip()}')
    print(f'- published log: {log.relative_to(WORKSPACE).as_posix()} -> {log.read_text(encoding="utf-8").strip()}')
    print(f'- published manifest exists: {service_manifest.is_file()}')
    print(f'- published frozen input exists: {service_frozen.is_file()}')
    print(f'- restored output: {restored_output.relative_to(WORKSPACE).as_posix()} -> {restored_output.read_text(encoding="utf-8").strip()}')
    print(f'- job work dir empty: {not any((JOB / "work").iterdir())}')
    print(f'- job service dir preserved: {(JOB / ".calcchain").is_dir()}')


if __name__ == '__main__':
    main()
