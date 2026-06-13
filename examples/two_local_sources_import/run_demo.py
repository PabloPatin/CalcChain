from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import tomlkit


WORKSPACE = Path(__file__).resolve().parent
REPO_ROOT = WORKSPACE.parents[1]
CORE_SRC = REPO_ROOT / "packages" / "core" / "src"
for path in (REPO_ROOT, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from calcchain_core import CalculationCore  # noqa: E402
from calcchain_core.rules import RuleSetType  # noqa: E402


JOB = WORKSPACE / "job"
CODE = WORKSPACE / "sources" / "code"
MEASUREMENTS = WORKSPACE / "sources" / "measurements"
CALIBRATION = WORKSPACE / "sources" / "calibration"
SERVICE_TARGET = WORKSPACE / "service_publish"
IMPORT_TARGET = WORKSPACE / "imported_results"


def main() -> None:
    reset_runtime()
    write_job_configs()

    core = CalculationCore(JOB)

    print("CalcChain example: code + two local input sources -> calculation -> import folder")
    print(f"calculation folder: {JOB / 'work'}")

    lock = core.create_build_lock()
    print(f"1. build lock created: {lock.build.name}")

    plan = core.validate_build()
    print("2. files planned for work dir:")
    for entry in sorted(plan.entries, key=lambda item: item.work_path):
        print(f"   - {entry.role}:{entry.source_name or 'code'} -> {entry.work_path}")

    core.build()
    print(f"3. work dir materialized: {JOB / 'work'}")

    manifest = core.run()
    print(f"4. run status: {manifest.to_dict()['run']['status']}")

    publish_result = core.publish()
    print(f"5. imported output files: {len(publish_result.groups[0].files)}")

    print_summary()


def reset_runtime() -> None:
    for path in (JOB, SERVICE_TARGET, IMPORT_TARGET):
        if path.exists():
            shutil.rmtree(path)
    JOB.mkdir(parents=True)


def write_job_configs() -> None:
    write_toml(
        JOB / "build.toml",
        {
            "build": {
                "name": "two-local-sources-import",
                "description": "Loads code plus measurement and calibration folders, then imports outputs locally.",
            },
            "code": {"source": {"type": "local", "path": str(CODE)}},
            "inputs": [
                {
                    "name": "measurements",
                    "source": {"type": "local", "path": str(MEASUREMENTS)},
                },
                {
                    "name": "calibration",
                    "source": {"type": "local", "path": str(CALIBRATION)},
                },
            ],
        },
    )
    write_toml(
        JOB / "run.toml",
        {
            "run": {
                "executable": sys.executable,
                "args": ["solver.py"],
                "cwd": ".",
                "timeout_seconds": 10,
            },
        },
    )
    write_toml(
        JOB / "publish.toml",
        {
            "publish": {"message": "import calculated results into local folder"},
            "service_target": {"type": "local", "path": str(SERVICE_TARGET)},
            "targets": [
                {
                    "name": "imported_results",
                    "type": "local",
                    "path": str(IMPORT_TARGET),
                    "rule_sets": ["calculation_outputs"],
                },
            ],
        },
    )
    (JOB / "rules.json").write_text(
        json.dumps(
            {
                "rule_sets": {
                    "calculation_outputs": {
                        "type": RuleSetType.OUTPUT.value,
                        "status": "approved",
                        "ensure_all_files": True,
                        "rules": [
                            {
                                "source": "results/(.*)",
                                "destination": "<capt:1>",
                            },
                        ],
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_toml(path: Path, data: dict) -> None:
    path.write_text(tomlkit.dumps(data), encoding="utf-8")


def print_summary() -> None:
    report = IMPORT_TARGET / "report.txt"
    summary = IMPORT_TARGET / "summary.json"
    service_manifest = SERVICE_TARGET / "manifest.json"

    print("\nSummary")
    print(f"- calculation folder: {JOB / 'work'}")
    print(f"- imported report: {report}")
    print(f"- imported summary: {summary}")
    print(f"- service manifest: {service_manifest}")
    print(f"- report content:\n{report.read_text(encoding='utf-8')}")


if __name__ == "__main__":
    main()
