#!/usr/bin/env python3
"""
demo_calcchain_module.py

Демонстрационный расчётный модуль:
- принимает на вход два файла;
- требует переменную окружения CALCCHAIN_DEMO_TOKEN;
- требует интерактивно ввести число меньше 10;
- имитирует выполнение расчёта;
- создаёт два выходных файла со статусом OK / ERROR.

Пример запуска:
    export CALCCHAIN_DEMO_TOKEN="demo-token"
    python demo_calcchain_module.py input_a.txt input_b.txt --out-dir demo_output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_ENV_VAR = "CALCCHAIN_DEMO_TOKEN"


def sha256_of_file(path: Path) -> str:
    """Возвращает SHA-256 файла."""
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def inspect_file(path: Path) -> dict[str, Any]:
    """Собирает простую информацию о входном файле."""
    text = path.read_text(encoding="utf-8", errors="replace")

    return {
        "path": str(path),
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "line_count": len(text.splitlines()),
        "sha256": sha256_of_file(path),
    }


def write_outputs(
    out_dir: Path,
    ok: bool,
    errors: list[str],
    input_files: list[dict[str, Any]],
    user_number: int | None,
) -> None:
    """Создаёт два выходных файла: текстовый статус и JSON-отчёт."""
    out_dir.mkdir(parents=True, exist_ok=True)

    status = "OK" if ok else "ERROR"

    status_text = [
        f"STATUS: {status}",
        f"TIME_UTC: {datetime.now(timezone.utc).isoformat()}",
        f"ENV_VAR_REQUIRED: {REQUIRED_ENV_VAR}",
        f"ENV_VAR_PRESENT: {str(REQUIRED_ENV_VAR in os.environ).lower()}",
        f"USER_NUMBER: {user_number if user_number is not None else 'not provided'}",
        "",
    ]

    if ok:
        status_text.extend(
            [
                "MESSAGE: Демонстрационный расчёт выполнен успешно.",
                "OUTPUT: Входные файлы проверены, расчёт имитирован, отчёт сформирован.",
            ]
        )
    else:
        status_text.append("MESSAGE: Демонстрационный расчёт завершился с ошибками.")
        status_text.append("ERRORS:")
        status_text.extend(f"- {error}" for error in errors)

    (out_dir / "result_status.txt").write_text("\n".join(status_text) + "\n", encoding="utf-8")

    report = {
        "ok": ok,
        "status": status,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "required_env_var": REQUIRED_ENV_VAR,
        "env_var_present": REQUIRED_ENV_VAR in os.environ,
        # Значение переменной окружения намеренно не записывается в отчёт.
        "env_var_value_saved": False,
        "user_number": user_number,
        "input_files": input_files,
        "simulated_work": {
            "steps": [
                "read_input_files",
                "validate_environment",
                "validate_interactive_parameter",
                "simulate_calculation",
                "write_artifacts",
            ],
            "description": "Фактический расчёт не выполняется; скрипт имитирует работу программного модуля.",
        },
        "errors": errors,
    }

    (out_dir / "result_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Демонстрационный модуль CalcChain: два входных файла, env-переменная, ввод числа и два выходных файла."
    )

    parser.add_argument("input_file_1", type=Path, help="Первый входной файл")
    parser.add_argument("input_file_2", type=Path, help="Второй входной файл")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("demo_output"),
        help="Папка для выходных файлов. По умолчанию: demo_output",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    errors: list[str] = []
    inspected_files: list[dict[str, Any]] = []
    user_number: int | None = None

    if REQUIRED_ENV_VAR not in os.environ:
        errors.append(f"Не задана обязательная переменная окружения {REQUIRED_ENV_VAR}.")

    for input_path in [args.input_file_1, args.input_file_2]:
        if not input_path.exists():
            errors.append(f"Входной файл не найден: {input_path}")
            continue

        if not input_path.is_file():
            errors.append(f"Путь не является файлом: {input_path}")
            continue

        inspected_files.append(inspect_file(input_path))

    try:
        raw_value = input("Введите целое число меньше 10: ").strip()
        user_number = int(raw_value)

        if user_number >= 10:
            errors.append("Введённое число должно быть меньше 10.")
    except ValueError:
        errors.append("Введённое значение не является целым числом.")
    except EOFError:
        errors.append("Не удалось прочитать число из stdin.")

    # Имитация полезной работы.
    if not errors:
        print("Входные данные приняты. Имитация расчёта...")
        time.sleep(1.0)
        print("Расчёт завершён успешно.")
    else:
        print("Обнаружены ошибки. Будут сформированы выходные файлы со статусом ERROR.")

    ok = len(errors) == 0
    write_outputs(
        out_dir=args.out_dir,
        ok=ok,
        errors=errors,
        input_files=inspected_files,
        user_number=user_number,
    )

    print(f"Выходные файлы записаны в папку: {args.out_dir}")
    print(f"- {args.out_dir / 'result_status.txt'}")
    print(f"- {args.out_dir / 'result_report.json'}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
