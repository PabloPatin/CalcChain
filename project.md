# CalcChain: текущее состояние проекта

## 1. Назначение

CalcChain сейчас состоит из двух частей:

- legacy-модулей `workspace_management` и `svn`, которые обслуживают старый workspace flow через CLI;
- нового ядра `calcchain_core`, которое реализует первый полный Python API цикл одного локального расчета: build, run, publish, restore и cleanup.

Новый внешний контракт первой версии - Python API. CLI в `main.py` пока относится к legacy flow и не является оболочкой над новым `calcchain_core`.

## 2. Legacy-часть проекта

### 2.1. CLI

Файл: `main.py`

Текущие команды:

- `init-ws`
- `check-ws`
- `save-results`

CLI создает `workspace_management.WorkspaceManager` и работает со старым форматом рабочей области.

### 2.2. WorkspaceManager

Файл: `workspace_management/manager.py`

`WorkspaceManager` обслуживает старый сценарий:

- читает `config.toml`;
- загружает исполняемые файлы и входные данные;
- читает `rules.json`;
- создает `config.lock.toml`;
- считает SHA-256 файлов рабочей области;
- сохраняет `info.json`;
- проверяет изменения файлов;
- читает `commit_config.toml`;
- выгружает результаты через file handlers.

Legacy flow не является новым ядром расчета: он не использует `build.toml`, `run.toml`, `publish.toml`, `manifest.json` нового формата и не предоставляет фасад `CalculationCore`.

### 2.3. File handlers

Файлы:

- `workspace_management/file_handlers/base.py`
- `workspace_management/file_handlers/local.py`
- `workspace_management/file_handlers/svn.py`
- `workspace_management/file_handlers/__init__.py`

Поддерживаемые handler-типы:

- `local` - локальная файловая система;
- `svn` - SVN через пакет `svn`.

Абстракции legacy-части:

- `BaseLoader` загружает файлы в workspace;
- `BaseRecorder` выгружает файлы из workspace;
- `LocalLoader` / `LocalRecorder` работают с локальными директориями;
- `SvnLoader` / `SvnRecorder` работают через SVN.

### 2.4. Rules и mapping

Файлы:

- `workspace_management/mapping/trans_map.py`
- `workspace_management/mapping/search_files.py`

Механика правил использует regex source patterns и destination templates. Поддерживаются маркеры вроде `<capt:...>`, `<path:name>`, `<path:stem>`, `<path:parent>`, `<source:desc>` и `<>`.

Эта legacy-механика также используется новым ядром через `calcchain_core/rules.py`, но новые форматы правил и статусы rule usage живут в `calcchain_core`.

### 2.5. SVN package

Файлы:

- `svn/src/client.py`
- `svn/src/commander.py`
- `svn/src/data_structures.py`
- `svn/src/exception.py`
- `svn/src/config.py`

Пакет `svn` содержит обертку над SVN CLI. Новый `calcchain_core` использует этот пакет для SVN source/target adapters.

### 2.6. Legacy-тесты

Legacy tests находятся в:

- `workspace_management/test/`
- `svn/test/`

Часть legacy tests устарела относительно текущей структуры кода. В workflow нового ядра основной проверяемый набор - `tests/test_core_*.py`.

## 3. Новое ядро `calcchain_core`

Новый пакет `calcchain_core` реализует воспроизводимый цикл одного расчета через Python API.

Основной фасад:

- `calcchain_core.api.CalculationCore`

Основные публичные операции:

- `create_build_lock()`
- `validate_build()`
- `build(dry_run=False)`
- `run()`
- `create_publish_lock()`
- `publish(dry_run=False)`
- `restore(RestoreRequest(...))`
- `cleanup(dry_run=False)`

### 3.1. Форматы нового ядра

Новые пользовательские и служебные форматы:

- `build.toml` - пользовательское описание code/input sources;
- `build.lock.toml` - зафиксированный build lock;
- `run.toml` - команда запуска, cwd, timeout, env и stdin-настройки;
- `publish.toml` - service target и result targets;
- `publish.lock.toml` - зафиксированные publish targets;
- `rules.json` - typed rule sets;
- `manifest.json` - фактический manifest расчета.

Local refs в новом ядре используют только `path`. SVN refs используют `location`, `path` и `revision`. Секреты моделируются names-only: значения secret env не записываются в config/manifest.

### 3.2. Основные модули нового ядра

- `models.py` - dataclass-модели форматов.
- `config.py` - чтение/запись TOML/JSON.
- `layout.py` - layout job/service/work/publication зон.
- `hash.py` - SHA-256 helpers.
- `sources.py` - local/SVN source adapters and registry.
- `rules.py` - typed rules поверх существующего regex mapping.
- `build_plan.py` - создание и валидация build lock/plan.
- `builder.py` - сборка `work/`, maps, snapshots, frozen inputs.
- `snapshot.py` - file snapshots.
- `frozen_inputs.py` - фиксация измененных input files.
- `run_config.py` - run config parsing.
- `runner.py` - запуск процесса через argv-list с `shell=False`.
- `output_classifier.py` - классификация outputs/logs/temp/ignored/unknown.
- `manifest.py` - запись manifest после build/run/publish.
- `targets.py` - local/SVN target adapters and registry.
- `publish.py` - publish lock, publish plan, manifest-last publication.
- `restore.py` - restore по manifest.
- `cleanup.py` - безопасная очистка `work/`.
- `api.py` - публичный фасад `CalculationCore`.

### 3.3. Принцип работы нового ядра

Новый цикл разделяет пользовательское намерение, lock-файлы, рабочую область и фактический manifest.

1. `create_build_lock()` читает `build.toml`, проверяет source refs и создает `build.lock.toml`.
2. `validate_build()` валидирует lock и rules, строит build plan.
3. `build()` собирает `job/work`, пишет build maps, build snapshot и служебные artifacts.
4. `run()` делает pre-run check, фиксирует frozen inputs при ручных изменениях input files, запускает процесс и пишет manifest.
5. `publish()` читает `publish.toml`, создает `publish.lock.toml`, публикует outputs/logs/service artifacts и пишет manifest последним.
6. `restore()` читает опубликованный или локальный `manifest.json`, восстанавливает файлы и проверяет hashes/tree hashes.
7. `cleanup()` удаляет только `job/work`, сохраняя `job/.calcchain`.

Restore не читает `build.toml`, `run.toml` или `publish.toml`; источником фактов является manifest и вложенные в него maps/sources/artifacts. Для frozen inputs restore может использовать опубликованную service-копию, если original job-local frozen input уже недоступен.

### 3.4. DFD нового ядра

```mermaid
flowchart LR
    user[External Entity: Python API caller]
    calc[Process: CalculationCore]

    build_cfg[(Data Store: build.toml)]
    run_cfg[(Data Store: run.toml)]
    publish_cfg[(Data Store: publish.toml)]
    rules[(Data Store: rules.json)]

    sources[External Entity: Local/SVN sources]
    targets[External Entity: Local/SVN targets]

    lock[(Data Store: build.lock.toml / publish.lock.toml)]
    work[(Data Store: job/work)]
    service[(Data Store: job/.calcchain)]
    manifest[(Data Store: manifest.json)]
    published[(Data Store: published outputs / service area)]
    restored[(Data Store: restored job)]

    user -->|calls API methods| calc
    build_cfg -->|build intent| calc
    run_cfg -->|run request| calc
    publish_cfg -->|publication request| calc
    rules -->|typed rule sets| calc

    calc -->|resolve/list/read| sources
    sources -->|code and inputs| calc

    calc -->|write locks| lock
    lock -->|validated facts| calc

    calc -->|assembled files| work
    work -->|snapshots and file groups| calc

    calc -->|maps, logs, snapshots, frozen inputs| service
    service -->|artifacts| manifest
    calc -->|manifest updates| manifest

    calc -->|publish result groups and service artifacts| targets
    targets -->|published refs| calc
    calc -->|published files| published
    published -->|published manifest and frozen inputs| calc

    manifest -->|restore facts| calc
    calc -->|restored work/service files| restored
    calc -->|cleanup| work
```

## 4. Текущие гарантии и ограничения нового ядра

Текущие гарантии:

- local refs используют `path` only;
- SVN refs валидируются на traversal/absolute path и userinfo credentials;
- run выполняется через argv-list и `shell=False`;
- timeout/cancel containment покрывает child processes с унаследованными stdout/stderr pipes;
- secret env хранится как names-only;
- manifest writer отклоняет credential-bearing SVN URLs;
- publish пишет manifest последним;
- restore service artifact writes ограничены `target_job_dir/.calcchain`;
- cleanup удаляет только `work/` и сохраняет service area.

Текущие ограничения:

- новый core не подключен к legacy CLI;
- GUI отсутствует;
- chains отсутствуют;
- auth/credentials lifecycle для нового core не реализован;
- integrity assessment block отсутствует;
- real SVN/network publish/restore в workflow не прогонялся; покрытие использует unit tests, local flow и adapter-level behavior;
- manifest provenance/trust policy находится вне текущей реализации.

## 5. Тестовое окружение `examples/test_workspace`

Папка:

- `examples/test_workspace`

Назначение: ручная проверка работоспособности нового `calcchain_core` через публичный `CalculationCore`.

Запуск из корня репозитория:

```powershell
python examples/test_workspace/run_demo.py
```

Что делает `run_demo.py`:

- пересоздает runtime-директории `job/`, `published_service/`, `published_outputs/`, `published_logs/`, `restored/`;
- пишет `build.toml`, `run.toml`, `publish.toml`, `rules.json` с абсолютными путями текущей машины;
- выполняет `create_build_lock()`;
- выполняет `validate_build()`;
- выполняет `build()`;
- вручную меняет `job/work/input/mesh.txt`, чтобы проверить frozen inputs;
- выполняет `run()`;
- выполняет `publish(dry_run=True)` и `publish()`;
- удаляет original job-local frozen inputs;
- выполняет `restore(..., dry_run=True)` и `restore()` из `published_service/manifest.json`;
- выполняет `cleanup(dry_run=True)` и `cleanup()`.

Ожидаемый результат:

- `examples/test_workspace/published_outputs/value.txt` содержит `CHANGED MESH`;
- `examples/test_workspace/published_logs/solver.log` содержит `done`;
- `examples/test_workspace/published_service/manifest.json` существует;
- `examples/test_workspace/published_service/frozen_inputs/input/mesh.txt` существует;
- `examples/test_workspace/restored/work/results/value.txt` содержит `CHANGED MESH`;
- `examples/test_workspace/job/work/` очищен;
- `examples/test_workspace/job/.calcchain/` сохранен.

Статические исходники примера:

- `examples/test_workspace/sources/code/solver.py`
- `examples/test_workspace/sources/input/input/mesh.txt`

Runtime-папки можно удалять: следующий запуск `run_demo.py` создаст их заново.

## 6. Актуальная проверка нового ядра

Основной набор тестов нового ядра:

```powershell
python -m unittest discover -s tests -p "test_core_*.py"
```

На текущем состоянии проекта core test suite проходил с результатом:

```text
Ran 85 tests ... OK
```

Для ручной smoke-проверки используется:

```powershell
python examples/test_workspace/run_demo.py
```
