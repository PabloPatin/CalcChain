# CalcChain Core Refactoring

Документ фиксирует целевое направление рефакторинга `calcchain_core`.

На текущем этапе ядро слишком плоское: большая часть модулей лежит прямо в корне пакета, а отдельные файлы, особенно `models.py`, `publish.py`, `restore.py`, `runner.py`, `builder.py`, `sources.py` и `targets.py`, имеют слишком широкую область ответственности.

Цель рефакторинга - разделить ядро по доменным зонам, не смешивая:

- общие утилиты;
- модели данных;
- чтение конфигураций;
- build lifecycle;
- run lifecycle;
- workspace/job artifacts;
- IO capabilities;
- publish/restore/cleanup;
- reports;
- mapping rules.

## Предлагаемая структура

```text
packages/core/src/calcchain_core/
  __init__.py
  api.py

  common/
    __init__.py
    errors.py
    hash.py
    logging.py
    status.py

  models/
    __init__.py
    common.py
    sources.py
    build.py
    run.py
    publish.py
    manifest.py
    rules.py

  config/
    __init__.py
    common.py
    build_config.py
    run_config.py
    publish_config.py
    rules_config.py

  io/
    __init__.py
    sources.py
    targets.py
    auth.py

  build/
    __init__.py
    plan.py
    builder.py
    frozen_inputs.py

  run/
    __init__.py
    runner.py

  workspace/
    __init__.py
    layout.py
    artifacts.py
    manifest.py
    snapshot.py
    maps.py
    output_classifier.py

  publish/
    __init__.py
    publish.py

  restore/
    __init__.py
    restore.py

  cleanup/
    __init__.py
    cleanup.py

  reports/
    __init__.py
    registry.py

  mapping/
    __init__.py
    search_files.py
    trans_map.py
```

## Почему не `artifacts/`

Папка `artifacts/` кажется слишком узким названием для файлов вроде `layout.py`, `manifest.py`, `snapshot.py`, `maps.py` и `output_classifier.py`.

Эти модули описывают не только артефакты, а весь слой данных рабочей области/job directory. Поэтому более точное имя - `workspace/`.

## Почему `restore` и `cleanup` отдельно от `publish`

`restore` и `cleanup` связаны с опубликованным состоянием, но не являются публикацией. Если положить их внутрь `publish/`, пакет начнет означать слишком много.

Лучше оставить:

- `publish/` - планирование и выполнение публикации;
- `restore/` - восстановление job из manifest/service layout;
- `cleanup/` - очистка рабочей директории.

## Разбиение моделей

`models.py` сейчас является главным кандидатом на разбиение. Его лучше разделить до переноса большей части логики, потому что модели являются общей точкой зависимостей.

Предлагаемое разбиение:

- `models/common.py` - общие enum/value types, schema helpers;
- `models/sources.py` - `SourceRef`, `TargetRef`, `SourceType`, `ArtifactRef`;
- `models/build.py` - `BuildConfig`, `BuildLock`, build-related entries;
- `models/run.py` - `RunConfig`, `RunStatus`, `JobStatus`;
- `models/publish.py` - `PublishConfig`, `PublishLock`;
- `models/manifest.py` - `Manifest`;
- `models/rules.py` - `RulesFile`, `RuleSet`, `RuleUse`, `RuleSetType`.

`models/__init__.py` должен переэкспортировать публичные модели, чтобы внешний импорт мог оставаться коротким.

## Порядок рефакторинга

Рефакторинг лучше выполнять поэтапно, без одного большого переноса.

1. Разнести `models.py` на пакет `models/`.
2. Перенести общие модули в `common/`.
3. Перенести `sources.py`, `targets.py`, `auth.py` в `io/`.
4. Перенести workspace/job data modules в `workspace/`.
5. Разделить чтение конфигов и rules helpers в `config/`.
6. Перенести build lifecycle в `build/`.
7. Перенести run lifecycle в `run/`.
8. Разделить publish, restore и cleanup.
9. Перенести reports в `reports/`.
10. Обновить импорты в `api.py`, тестах и примерах.
11. Удалить старые корневые модули после перевода внутренних импортов на новую структуру.

## Старые корневые модули

Так как у проекта пока мало внешних зависимостей от старого layout, лучше не держать compatibility shims ради сохранения исторических импортов.

После переноса логики код, тесты и примеры должны импортировать модули напрямую из новых доменных пакетов: `common/`, `io/`, `workspace/`, `build/`, `run/`, `publish/`, `restore/`, `cleanup/`, `reports/`.

## Целевая граница ответственности

После рефакторинга `calcchain_core` должен оставаться ядром расчётного lifecycle:

- built-in local IO;
- build/run/publish/restore;
- manifest/snapshot/layout;
- правила mapping;
- интеграция runtime capabilities через `calcchain_capabilities`.

`calcchain_core` не должен зависеть от `calcchain_plugin_system`.

Система плагинов остается отдельным пакетом и только подготавливает runtime capabilities, которые затем передаются в core.
