from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from calcchain_core.config import write_manifest
from calcchain_core.errors import RestoreError
from calcchain_core.hash import sha256_file, tree_sha256
from calcchain_core.layout import JobLayout
from calcchain_core.models import Manifest
from calcchain_core.restore import RestoreRequest, restore_from_manifest
from calcchain_core.sources import SourceRegistry


class TestCoreRestore(unittest.TestCase):
    def test_restore_uses_frozen_inputs_when_original_input_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, target = _restore_fixture(root)

            result = restore_from_manifest(RestoreRequest(manifest_path, target), SourceRegistry())

            self.assertEqual(result.status, 'restored')
            self.assertEqual((target / 'work' / 'solver.py').read_text(encoding='utf-8'), 'print("ok")\n')
            self.assertEqual((target / 'work' / 'input' / 'mesh.txt').read_text(encoding='utf-8'), 'frozen mesh\n')
            self.assertTrue((target / '.calcchain' / 'build' / 'build_lock.json').is_file())
            self.assertTrue((target / '.calcchain' / 'snapshots' / 'build_snapshot.json').is_file())

    def test_restore_fails_when_required_frozen_input_source_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, target = _restore_fixture(root)
            data = json.loads(manifest_path.read_text(encoding='utf-8'))
            frozen_root = Path(data['build']['inputs'][1]['sources'][0]['path'])
            for path in frozen_root.rglob('*'):
                if path.is_file():
                    path.unlink()

            with self.assertRaises(RestoreError):
                restore_from_manifest(RestoreRequest(manifest_path, target), SourceRegistry())

    def test_restore_dry_run_verifies_sources_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, target = _restore_fixture(root)

            result = restore_from_manifest(RestoreRequest(manifest_path, target, dry_run=True), SourceRegistry())

            self.assertEqual(result.status, 'planned')
            self.assertFalse((target / 'work').exists())
            self.assertIn('solver.py', result.verified_hashes)

    def test_restore_uses_published_service_copy_of_frozen_inputs_after_original_job_is_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, target, original_job = _published_restore_fixture(root)
            for path in sorted(original_job.rglob('*'), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()
            original_job.rmdir()

            result = restore_from_manifest(RestoreRequest(manifest_path, target), SourceRegistry())

            self.assertEqual(result.status, 'restored')
            self.assertEqual((target / 'work' / 'input' / 'mesh.txt').read_text(encoding='utf-8'), 'published mesh\n')

    def test_restore_rejects_snapshot_key_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, target = _restore_fixture(root)
            data = json.loads(manifest_path.read_text(encoding='utf-8'))
            data['snapshots'] = {'../../../escape': data['snapshots']['build']}
            write_manifest(Manifest.from_dict(data), manifest_path)

            with self.assertRaises(RestoreError):
                restore_from_manifest(RestoreRequest(manifest_path, target), SourceRegistry())

            self.assertFalse((root / 'escape_snapshot.json').exists())
            self.assertFalse((target.parent / 'escape_snapshot.json').exists())


def _restore_fixture(root: Path) -> tuple[Path, Path]:
    source_code = root / 'source_code'
    source_code.mkdir()
    (source_code / 'solver.py').write_text('print("ok")\n', encoding='utf-8')
    missing_input = root / 'missing_input'
    frozen = root / 'published_service' / 'frozen_inputs'
    frozen.mkdir(parents=True)
    (frozen / 'input' / 'mesh.txt').parent.mkdir(parents=True)
    (frozen / 'input' / 'mesh.txt').write_text('frozen mesh\n', encoding='utf-8')
    service = root / 'published_service'
    (service / 'build.lock.toml').write_text('lock\n', encoding='utf-8')
    (service / 'snapshots').mkdir(exist_ok=True)
    (service / 'snapshots' / 'build_snapshot.json').write_text('{}\n', encoding='utf-8')
    code_sha = sha256_file(source_code / 'solver.py')
    input_sha = sha256_file(frozen / 'input' / 'mesh.txt')
    manifest = Manifest.from_dict(
        {
            'job': {'status': 'Published', 'job_dir': str(root / 'original')},
            'build': {
                'lock': _artifact(service / 'build.lock.toml'),
                'code': {
                    'name': 'solver',
                    'tree_sha256': tree_sha256([('solver.py', code_sha)]),
                    'source': {'type': 'local', 'path': str(source_code)},
                    'map': [{'sha256': code_sha, 'source_path': 'solver.py', 'work_path': 'solver.py'}],
                },
                'inputs': [
                    {
                        'name': 'mesh',
                        'tree_sha256': tree_sha256([('input/mesh.txt', '0' * 64)]),
                        'source': {'type': 'local', 'path': str(missing_input)},
                        'map': [{'sha256': '0' * 64, 'source_path': 'mesh.txt', 'work_path': 'input/mesh.txt'}],
                    },
                    {
                        'name': 'frozen_inputs',
                        'tree_sha256': tree_sha256([('input/mesh.txt', input_sha)]),
                        'sources': [{'type': 'local', 'path': str(frozen)}],
                        'map': [
                            {
                                'sha256': input_sha,
                                'source_path': 'input/mesh.txt',
                                'work_path': 'input/mesh.txt',
                                'target_path': 'input/mesh.txt',
                            },
                        ],
                    },
                ],
            },
            'snapshots': {'build': _artifact(service / 'snapshots' / 'build_snapshot.json')},
        },
    )
    manifest_path = root / 'manifest.json'
    write_manifest(manifest, manifest_path)
    return manifest_path, root / 'restored'


def _artifact(path: Path) -> dict:
    return {'sha256': sha256_file(path), 'sources': [{'type': 'local', 'path': str(path)}]}


def _published_restore_fixture(root: Path) -> tuple[Path, Path, Path]:
    source_code = root / 'source_code'
    source_code.mkdir()
    (source_code / 'solver.py').write_text('print("ok")\n', encoding='utf-8')
    original_job = root / 'original_job'
    original_frozen = original_job / '.calcchain' / 'frozen_inputs'
    service = root / 'published_service'
    service_frozen = service / 'frozen_inputs'
    (original_frozen / 'input').mkdir(parents=True)
    (service_frozen / 'input').mkdir(parents=True)
    (original_frozen / 'input' / 'mesh.txt').write_text('published mesh\n', encoding='utf-8')
    (service_frozen / 'input' / 'mesh.txt').write_text('published mesh\n', encoding='utf-8')
    (service / 'publish.lock.toml').write_text('publish lock\n', encoding='utf-8')
    code_sha = sha256_file(source_code / 'solver.py')
    frozen_sha = sha256_file(service_frozen / 'input' / 'mesh.txt')
    manifest = Manifest.from_dict(
        {
            'job': {'status': 'Published', 'job_dir': str(original_job)},
            'build': {
                'code': {
                    'name': 'solver',
                    'tree_sha256': tree_sha256([('solver.py', code_sha)]),
                    'source': {'type': 'local', 'path': str(source_code)},
                    'map': [{'sha256': code_sha, 'source_path': 'solver.py', 'work_path': 'solver.py'}],
                },
                'inputs': [
                    {
                        'name': 'mesh',
                        'tree_sha256': tree_sha256([('input/mesh.txt', '0' * 64)]),
                        'source': {'type': 'local', 'path': str(root / 'missing_input')},
                        'map': [{'sha256': '0' * 64, 'source_path': 'mesh.txt', 'work_path': 'input/mesh.txt'}],
                    },
                    {
                        'name': 'frozen_inputs',
                        'tree_sha256': tree_sha256([('input/mesh.txt', frozen_sha)]),
                        'sources': [{'type': 'local', 'path': str(original_frozen)}],
                        'map': [
                            {
                                'sha256': frozen_sha,
                                'source_path': 'input/mesh.txt',
                                'work_path': 'input/mesh.txt',
                                'target_path': 'input/mesh.txt',
                            },
                        ],
                    },
                ],
            },
            'publication': {'lock': _artifact(service / 'publish.lock.toml')},
        },
    )
    manifest_path = service / 'manifest.json'
    write_manifest(manifest, manifest_path)
    return manifest_path, root / 'restored_from_published', original_job


if __name__ == '__main__':
    unittest.main()
