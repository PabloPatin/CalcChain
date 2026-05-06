# CalcChain Test Workspace

Минимальное локальное окружение для ручной проверки нового `calcchain_core`.

Запуск из корня репозитория:

```powershell
python examples/test_workspace/run_demo.py
```

Скрипт:

- пересоздает runtime-директории `job/`, `published_*`, `restored/`;
- пишет `build.toml`, `run.toml`, `publish.toml`, `rules.json` с абсолютными путями текущей машины;
- выполняет `CalculationCore.create_build_lock()`;
- выполняет `validate_build()`;
- выполняет `build()`;
- меняет input в `job/work/input/mesh.txt`, чтобы проверить frozen inputs;
- выполняет `run()`;
- выполняет `publish(dry_run=True)` и `publish()`;
- удаляет original job-local frozen inputs;
- выполняет `restore(... dry_run=True)` и `restore()` из опубликованного manifest;
- выполняет `cleanup(dry_run=True)` и `cleanup()`.

Ожидаемый результат:

- `published_outputs/value.txt` содержит `CHANGED MESH`;
- `published_logs/solver.log` содержит `done`;
- `published_service/manifest.json` существует;
- `published_service/frozen_inputs/input/mesh.txt` существует;
- `restored/work/results/value.txt` содержит `CHANGED MESH`;
- `job/work/` очищен, а `job/.calcchain/` сохранен.

Static source files лежат в:

- `sources/code/solver.py`
- `sources/input/input/mesh.txt`

Runtime-папки можно удалять: они будут пересозданы следующим запуском `run_demo.py`.
