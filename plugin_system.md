# Решения по системе плагинов

## Упаковка и Python runtime

CalcChain должен ориентироваться на дистрибутив в виде директории приложения, а не на single-file `.exe`, внутрь которого запечен весь код ядра.

Предпочтительная структура:

```text
CalcChain/
  CalcChain.exe
  runtime/
    python.exe
    ...
  app/
    core/
    plugin_api/
    ui/
  plugins/
    ...
  plugin_envs/
    ...
  wheelhouse/
    ...
```

`CalcChain.exe` является launcher-ом / desktop entry point. Код приложения, стабильный plugin API, sidecar Python runtime и plugins лежат рядом как управляемые части дистрибутива.

Preinstalled plugins и будущие external Python plugins должны использовать один plugin API и один механизм регистрации. Они различаются источником установки и политикой доверия.

Зависимости external plugin-ов нельзя устанавливать в `CalcChain.exe` или global Python. Они должны устанавливаться в active plugin environment, которым управляет Python runtime.

## UI и удаленный доступ

Конечное решение по интерфейсу: только web UI.

Core должен быть доступен через backend API. Web UI подключается к backend API локально или удаленно в зависимости от режима работы.

Локальный режим:

```text
Web UI
  -> local backend
  -> core
```

Удаленный режим:

```text
Web UI
  -> remote backend
  -> server-side core
```

Offline mode обязателен. В offline mode удаленные подключения запрещены: UI может работать только с локальным backend/core, а dependency installation и другие операции не должны требовать сетевого доступа.

Plugin-specific UI на ближайшем этапе должен строиться через schema-driven подход. В качестве первого готового решения выбираем JSON Forms: plugin/capability предоставляет JSON Schema / UI schema / descriptors, а web UI рендерит формы по этим данным.

Если JSON Forms окажется недостаточно гибким для сценариев CalcChain, позже можно спроектировать самописный interaction/descriptor слой. На текущем этапе plugin-и не должны поставлять собственные frontend components как основной механизм расширения UI.

## Структура plugin-а

Plugin поставляется как директория с metadata-файлом и Python package:

```text
plugins/
  calcchain_git/
    plugin.json
    calcchain_git/
      plugin.py
    wheels/
      ...
```

`plugin.json` описывает загрузку, совместимость, зависимости и опциональные декларативные подсказки. Возможности plugin-а определяются тем, какие capabilities он зарегистрирует при запуске.

Обязательные поля:

- `schema_version`;
- `plugin_id`;
- `plugin_version`;
- `requires_plugin_api`;
- `python_requires`;
- `entrypoint`;
- `dependencies`.

Version specifiers используют Python/PEP 440 style, например `>=1.0,<2.0`.

Пример `plugin.json`:

```json
{
  "schema_version": "1.0",
  "plugin_id": "calcchain.git",
  "plugin_version": "0.1.0",
  "requires_plugin_api": ">=1.0,<2.0",
  "python_requires": ">=3.12,<3.13",
  "entrypoint": "calcchain_git.plugin:GitPlugin",
  "dependencies": {
    "mode": "wheels",
    "wheels_path": "wheels",
    "requirements": "requirements.txt"
  },
  "declared_capabilities": [
    {"namespace": "source", "id": "git"},
    {"namespace": "target", "id": "git"}
  ]
}
```

`entrypoint` использует формат `module.path:ClassName`, например `calcchain_git.plugin:GitPlugin`. Он должен указывать на модуль внутри package plugin-а, а не на произвольный путь в файловой системе.

Используем только режим `wheels`: plugin поставляет wheel-файлы рядом с собой, а требования описывает в pip-compatible requirements-файле, например `requirements.txt`.

При активации набора plugin-ов программа собирает requirements всех активных plugin-ов, использует wheel-файлы из plugin-каталогов и общего wheelhouse, затем устанавливает совместимый набор зависимостей через `pip` в активное plugin environment.

Vendored dependencies в виде уже распакованных пакетов в `deps/` не считаются поддерживаемым режимом поставки.

Установка зависимостей не должна выполняться при обычном старте приложения.

## Dependency environment

Для активных plugin-ов используется один общий active plugin environment. Это нужно потому, что plugin-и загружаются в один Python runtime и должны использовать один согласованный набор зависимостей.

Environment хранится в portable-структуре рядом с дистрибутивом, без привязки к OS-specific appdata:

```text
CalcChain/
  plugin_envs/
    <env_hash>/
      site-packages/
      plugin-env.lock.json
```

`env_hash` вычисляется по данным, которые влияют на окружение:

- версия Python runtime;
- версия plugin API;
- список активных plugin-ов: `plugin_id`, `plugin_version`;
- hash requirements-файла каждого активного plugin-а;
- версия installer backend, на ближайшем этапе `pip`;
- hash wheel manifest-ов, если они есть.

Сборка environment должна выполняться во временную директорию. Только после успешной установки зависимостей, проверки wheel hashes и записи `plugin-env.lock.json` временная директория заменяет/публикует готовый `<env_hash>`.

Отдельный marker-файл вроде `.ready` не используем. Готовность environment определяется наличием корректного `plugin-env.lock.json`, совпадением `env_hash` и успешной проверкой записанных hash-ов.

`plugin-env.lock.json` является служебным lock-файлом окружения plugin-ов, а не расчетным lock-файлом. Он хранит:

- `env_hash`;
- версию Python runtime;
- версию plugin API;
- активные plugin-и и их версии;
- requirements-файлы и их SHA-256;
- resolved dependencies;
- wheel-файлы, использованные при установке, и их SHA-256.

Wheel-файлы должны иметь зафиксированные SHA-256, чтобы после сборки/добавления plugin-а нельзя было незаметно подменить dependency wheel.

Предпочтительный вариант:

```text
plugins/
  calcchain_git/
    wheels.lock.json
    wheels/
      GitPython-3.1.44-py3-none-any.whl
```

`wheels.lock.json` должен содержать имена wheel-файлов и их SHA-256. При активации plugin-ов CalcChain проверяет wheel-файлы перед установкой через `pip`, а фактически использованные wheel hashes дополнительно записывает в `plugin-env.lock.json`.

Если active plugin set изменился, `env_hash` меняется и требуется новый active plugin environment. Переключение active set должно требовать перезапуска plugin runtime или приложения, потому что Python плохо выгружает уже импортированные modules.

`declared_capabilities` является опциональной metadata для UI, preflight checks и диагностики. Источником истины остается фактическая регистрация capabilities в `plugin.register(context)`. Если plugin указал `declared_capabilities`, но фактическая регистрация с ними не совпала, это должно считаться ошибкой активации или строгим warning.

Enabled/disabled state не хранится в `plugin.json`. Этот файл принадлежит plugin package. Состояние включения plugin-а должно храниться отдельно в настройках пользователя/приложения, например в `plugins.json`.

## Добавление и активация plugin-ов

Добавление plugin-а и активация plugin-а - разные процессы.

Добавление означает, что plugin package появился в plugin-каталоге и прошел базовую проверку metadata. Активация означает, что plugin включен в текущий набор, его зависимости согласованы, Python entrypoint импортирован, а capabilities зарегистрированы.

Общий flow:

```text
discover
  -> read metadata
  -> check metadata
  -> record installed plugin
  -> select enabled plugins
  -> check compatibility
  -> resolve/install dependencies
  -> import entrypoint
  -> register capabilities
  -> activate set
```

### Добавление plugin-а

```text
plugin package copied to plugins/
  -> PluginDiscovery finds plugin.json
  -> PluginMetadataReader reads metadata
  -> PluginValidator checks metadata shape
  -> PluginRepository records installed plugin
```

Ответственность:

- `PluginDiscovery` сканирует plugin directories и ищет `plugin.json`; Python-код plugin-а на этом этапе не импортируется.
- `PluginMetadataReader` читает `plugin.json`, проверяет JSON/schema_version и строит `PluginMetadata`.
- `PluginValidator` проверяет обязательные поля, entrypoint, version specifiers, dependencies block и optional `declared_capabilities`.
- `PluginRepository` хранит список установленных plugin-ов, пути к ним и metadata. Наличие в repository не означает, что plugin активен.

### Выбор активного набора

Enabled/disabled state хранится отдельно от `plugin.json`, например:

```json
{
  "enabled_plugins": [
    "calcchain.svn",
    "calcchain.git"
  ]
}
```

Ответственность:

- `PluginSettings` хранит пользовательский enabled/disabled state.
- `PluginActivationPlanner` берет enabled plugin ids, проверяет, что они установлены, и строит план активации.

### Проверка совместимости

Для выбранного набора plugin-ов проверяются:

- `requires_plugin_api`;
- `python_requires`;
- дубли `plugin_id`;
- preliminary conflicts по `declared_capabilities`, если они указаны.

`declared_capabilities` не являются источником истины, но позволяют заранее поймать часть конфликтов до импорта plugin-а.

### Зависимости и active plugin environment

Для активного набора plugin-ов:

```text
enabled plugins
  -> collect requirements files
  -> collect plugin wheels/
  -> collect shared wheelhouse
  -> pip resolve/install into active plugin environment
```

Ответственность:

- `PluginDependencyPlanner` собирает requirements всех активных plugin-ов и локальные wheel sources.
- `PluginEnvironmentManager` вычисляет hash активного набора plugin-ов и requirements, создает или переиспользует active plugin environment и вызывает sidecar `runtime/python.exe -m pip ...`.
- `pip` выполняет фактическое разрешение зависимостей и сообщает конфликты.

CalcChain не должен писать собственный dependency resolver. Он управляет requirements, wheel sources, active environment и понятной диагностикой ошибок.

Если локальных wheels недостаточно и online install запрещен или завершился ошибкой, программа должна показать пользователю список недостающих зависимостей и предложить добавить wheel-файлы в plugin wheelhouse или общий wheelhouse.

### Импорт plugin-а

После готовности active plugin environment:

```text
PluginImporter imports entrypoint
  -> instantiate plugin object
```

Ответственность:

- `PluginImporter` добавляет active plugin environment и plugin package paths в controlled import context.
- `PluginImporter` импортирует `entrypoint` из metadata.
- Импорт по произвольному пути из пользовательского config запрещен.
- Plugin должен импортировать публичный `plugin_api`, а не приватную структуру core.

### Регистрация capabilities

После импорта `PluginManager` создает ограниченный `PluginContext` и вызывает:

```python
plugin.register(context)
```

Ответственность:

- `PluginManager` вызывает `register`, ловит plugin errors и управляет активацией.
- Registrar-ы проверяют owner, namespace/id conflicts и сохраняют adapter/provider objects.
- Если `declared_capabilities` указаны, фактическая регистрация должна быть с ними совместима; несовпадение считается ошибкой активации или строгим warning.

### Завершение активации

Активация должна быть атомарной на уровне активного набора: либо весь enabled set успешно активирован, либо приложение показывает ошибку и остается на предыдущем рабочем наборе plugin-ов.

После успешной активации core получает готовые registries capabilities и может использовать source/target/report/auth adapters.

## Регистрация plugin-а

После проверки metadata `PluginManager` импортирует `entrypoint`, создает plugin object и вызывает:

```python
plugin.register(context)
```

Plugin регистрирует capabilities через выданный `context`:

```python
class GitPlugin:
    plugin_id = "calcchain.git"
    plugin_version = "0.1.0"

    def register(self, context):
        backend = GitBackend()
        context.sources.register("git", GitSourceAdapter(backend), owner=self.plugin_id)
        context.targets.register("git", GitTargetAdapter(backend), owner=self.plugin_id)
```

В этом примере plugin регистрирует две capabilities: `source:git` и `target:git`.

`PluginManager` должен проверять:

- уникальность `plugin_id`;
- совместимость `requires_plugin_api` и `python_requires`;
- отсутствие конфликтов capability id, например двух разных `source:git`;
- что plugin импортирует публичный `plugin_api`, а не зависит от приватной структуры core.

## PluginContext и registrars

Plugin не получает прямой доступ к `PluginManager` или внутренним registry ядра. Для регистрации возможностей ему передается ограниченный `PluginContext`.

Примерная форма:

```python
class PluginContext:
    sources: SourceRegistrar
    targets: TargetRegistrar
    reports: ReportRegistrar
    auth: AuthRegistrar
```

Внутри core могут существовать runtime registry, но внешний plugin API должен работать через registrar-ы.

Базовый registrar отвечает за общие правила регистрации:

- проверить, что capability id является непустой строкой;
- проверить, что owner совпадает с текущим `plugin_id`;
- запретить повторную регистрацию одного capability id в одном namespace;
- сохранить связь `namespace:id -> plugin_id`;
- сохранить adapter/provider object;
- вернуть ошибку регистрации через публичный plugin API, а не через внутренние ошибки core.

Каждый специализированный registrar задает свой namespace и ожидаемый контракт adapter-а:

```text
SourceRegistrar  -> namespace "source",  пример id "git"
TargetRegistrar  -> namespace "target",  пример id "git"
ReportRegistrar  -> namespace "report",  пример id "html"
AuthRegistrar    -> namespace "auth",    пример id "env" или "interactive_prompt"
```

Одинаковые id в разных namespaces допустимы. Например один plugin может зарегистрировать `source:git` и `target:git`.

Для `AuthRegistrar` id обозначает auth provider, а не auth scheme. Несколько auth providers могут поддерживать одну scheme через `can_handle(requirement)`.

Пример интерфейса registrar-а:

```python
class SourceRegistrar:
    def register(self, id: str, adapter: SourceAdapter, *, owner: str) -> None:
        ...
```

Для всех registrar-ов правило одинаковое: plugin регистрирует только capabilities, а lifecycle расчета, lock-файлы и manifest остаются под управлением core.

## Модель безопасности plugin-ов

Python plugin, загруженный in-process, считается trusted code. Текущая модель безопасности не является sandbox-ом: plugin технически имеет права процесса CalcChain.

Безопасность строится на следующих правилах:

- plugin activation выполняется явно через настройки/manager, а не через пользовательский `build.toml` или `publish.toml`;
- пользовательский config может ссылаться только на уже активированную capability через `type`;
- импорт plugin-а по произвольному пути из пользовательского config запрещен;
- lock-файлы и manifest остаются под управлением core;
- dependency wheels проверяются по SHA-256;
- активация plugin set должна быть атомарной.

### Секреты

Запрет userinfo в SVN/Git/S3 URL и другие protocol-specific проверки являются ответственностью соответствующих source/target adapter-ов.

Core отвечает за то, что lock-файлы и manifest не содержат секретных значений.

Правило для lock/manifest:

```text
secret detected -> error -> file is not written
```

Core не должен молча заменять секреты на `****` в lock/manifest, потому что это может испортить воспроизводимость ref-а. Маскирование применяется для логов, reports и exception messages.

Core должен иметь secret guard/redactor:

- known secret values, выданные через auth context, проверяются перед записью lock/manifest;
- common secret patterns могут дополнительно проверяться как defense-in-depth;
- сообщения в logger/errors/reports проходят через redaction/secret masking.

Секреты не должны попадать в:

- пользовательские config-файлы;
- lock-файлы;
- manifest;
- логи;
- reports;
- exception messages.

### Path containment

Path containment в plugin API не является sandbox-ом. Он нужен, чтобы core не выполнял опасные записи на основании ошибочных данных, полученных от plugin-а или внешнего источника.

Правила:

- `SourceAdapter.list_files()` должен возвращать только относительные POSIX paths;
- absolute paths и traversal запрещены;
- core дополнительно проверяет paths перед записью в `job/work`, service area или reports;
- `ReportAdapter` не пишет файлы сам, а возвращает content;
- `TargetAdapter.write_file()` получает от core только safe relative path и дополнительно проверяет containment внутри своего target root.

Эти проверки защищают от ошибок plugin-а и недоверенных внешних данных, но не от злонамеренного in-process plugin-а.

### Dependency integrity

Wheel-файлы plugin-ов должны иметь SHA-256 в `wheels.lock.json`. Перед установкой dependency environment CalcChain проверяет hashes.

Фактически использованные wheels и их hashes записываются в `plugin-env.lock.json`.

Если wheel изменился после проверки или установленное environment не соответствует `plugin-env.lock.json`, environment считается недействительным и должен быть пересобран.

## Source/target config flow

Core не должен знать plugin-specific поля source/target ref. Он читает source/target block как raw `dict`, по полю `type` находит зарегистрированный adapter и передает dict adapter-у.

Общий flow:

```text
user source/target config
  -> core reads raw dict
  -> core checks required generic field "type"
  -> core finds adapter by type
  -> adapter.validate_config(raw_ref)
  -> adapter.resolve_lock_ref(raw_ref)
  -> adapter.validate_lock_ref(lock_ref)
  -> core adds plugin metadata
  -> core writes lock file
```

Core делает только generic validation:

- ref block является table/object;
- `type` существует;
- `type` является строкой;
- capability с таким `type` зарегистрирована;
- ref serializable в TOML/JSON.

Core не должен интерпретировать plugin-specific поля вроде `branch`, `submodules`, `bucket`, `region`, `depth` и т.п.

Пример user source config:

```toml
[code.source]
type = "git"
location = "https://example.org/solver.git"
path = "solver"
revision = "main"
submodules = true
depth = 1
```

Core передает adapter-у:

```python
{
    "type": "git",
    "location": "https://example.org/solver.git",
    "path": "solver",
    "revision": "main",
    "submodules": True,
    "depth": 1,
}
```

Adapter возвращает lock-ready dict, например:

```python
{
    "type": "git",
    "location": "https://example.org/solver.git",
    "path": "solver",
    "revision": "b4f9c0e8d3...",
    "submodules": True,
}
```

Core пишет lock-файл сам. Plugin не пишет lock-файлы.

Core должен добавлять metadata о plugin-е, который владеет capability:

```toml
[code.source.plugin]
id = "calcchain.git"
version = "0.1.0"
```

Lock-ready dict, который возвращает adapter, должен быть:

- serializable;
- concrete enough для lock;
- без секретов;
- с тем же `type`;
- без userinfo в URL;
- без path traversal в path-like полях;
- валидируемым через `validate_lock_ref()`;
- без runtime-only объектов.

Для target refs действует та же схема: core читает raw target dict, находит target adapter по `type`, adapter возвращает lock-ready target dict, core добавляет plugin metadata и пишет `publish.lock.toml`.

## SourceAdapter

`SourceAdapter` отвечает за работу с источником файлов: проверяет пользовательское описание источника, конкретизирует его для lock-файла и читает файлы во время build/restore.

Основной flow:

```text
raw source config
  -> validate_config()
  -> resolve_lock_ref()
  -> core writes build.lock.toml
  -> validate_lock_ref()
  -> list_files()
  -> read_file()
```

Обязательный интерфейс:

```python
class SourceAdapter:
    def validate_config(self, raw_ref: dict, context: SourceContext) -> None:
        ...

    def resolve_lock_ref(self, raw_ref: dict, context: SourceContext) -> dict:
        ...

    def validate_lock_ref(self, lock_ref: dict, context: SourceContext) -> None:
        ...

    def list_files(self, lock_ref: dict, context: SourceContext) -> list[str]:
        ...

    def read_file(self, lock_ref: dict, relative_path: str, context: SourceContext) -> bytes:
        ...

    def is_versionable(self, lock_ref: dict, context: SourceContext) -> bool:
        ...
```

`validate_config()` проверяет пользовательский source block до создания lock: обязательные поля, типы значений, запрещенные поля, отсутствие секретов, корректность URL/path/revision.

`resolve_lock_ref()` преобразует пользовательский source block в конкретный lock-ready dict. Например `svn revision = "HEAD"` превращается в конкретный номер ревизии, а будущий `git branch = "main"` - в commit hash. Plugin возвращает данные, но lock-файл пишет только core.

`validate_lock_ref()` проверяет, что ref из lock уже конкретный и пригоден для воспроизводимого build.

`list_files()` возвращает список файлов источника. Пути должны быть относительными, использовать POSIX separators и не содержать директорий.

`read_file()` возвращает содержимое одного файла как `bytes`.

`is_versionable()` сообщает, имеет ли источник стабильную версионную идентичность.

Core передает adapter-у source block как `dict`, потому что core не должен знать все plugin-specific поля. Adapter обязан вернуть lock-ready dict, который:

- serializable;
- concrete;
- без секретов;
- с тем же `type`;
- валидируется самим adapter-ом.

Опционально в будущем `SourceAdapter` может предоставлять `config_schema()` для UI/CLI wizard и auth requirements для запроса credentials. Эти методы не обязательны для базового build-flow.

`SourceContext` создает core перед вызовом adapter-а. Plugin не создает context сам и не получает прямой доступ к `PluginManager`.

Минимальный состав `SourceContext`:

```python
class SourceContext:
    plugin_id: str
    source_type: str
    operation: str
    auth: AuthService | None
    logger: PluginLogger
```

Поля:

- `plugin_id` - plugin, который зарегистрировал текущую source capability;
- `source_type` - значение `type` из source ref, например `local`, `svn`, `git`;
- `operation` - текущая операция adapter-а, например `validate_config`, `resolve_lock_ref`, `list_files`;
- `auth` - controlled access к будущей системе аутентификации через `AuthService`.
- `logger` - controlled logger для plugin-а; сообщения должны проходить через redaction/secret masking.

В будущем в `SourceContext` можно добавить cache/temp dirs, network settings и cancellation token, не меняя общий принцип работы adapter-а.

## TargetAdapter

`TargetAdapter` отвечает за работу с целями публикации: проверяет пользовательское описание target, конкретизирует его для publish lock и записывает файлы во время publish.

Основной flow:

```text
raw target config
  -> validate_config()
  -> resolve_lock_ref()
  -> core writes publish.lock.toml
  -> validate_lock_ref()
  -> ensure_root()
  -> write_file()
```

Обязательный интерфейс:

```python
class TargetAdapter:
    def validate_config(self, raw_ref: dict, context: TargetContext) -> None:
        ...

    def resolve_lock_ref(self, raw_ref: dict, context: TargetContext) -> dict:
        ...

    def validate_lock_ref(self, lock_ref: dict, context: TargetContext) -> None:
        ...

    def ensure_root(self, lock_ref: dict, context: TargetContext) -> dict:
        ...

    def write_file(
        self,
        lock_ref: dict,
        relative_path: str,
        data: bytes,
        context: TargetContext,
    ) -> PublishedRef:
        ...

    def is_versionable(self, lock_ref: dict, context: TargetContext) -> bool:
        ...
```

`validate_config()` проверяет пользовательский target block до создания publish lock: обязательные поля, типы значений, запрещенные поля, отсутствие секретов, корректность URL/path/revision.

`resolve_lock_ref()` преобразует пользовательский target block в конкретный lock-ready dict. Например `svn revision = "HEAD"` должен быть преобразован в конкретную ревизию или другой стабильный идентификатор целевого источника, если target это поддерживает.

`validate_lock_ref()` проверяет, что target ref из publish lock уже конкретный и пригоден для публикации.

`ensure_root()` создает или проверяет корневую директорию/область публикации и возвращает нормализованный target ref, если target требует уточнения после создания root.

`write_file()` записывает один файл по target-relative path и возвращает `PublishedRef`, который core сможет включить в publication facts/manifest.

`is_versionable()` сообщает, имеет ли target стабильную версионную идентичность. Core использует это для политики публикации, например чтобы блокировать или предупреждать выгрузку в версионируемый target, если запуск зависит от неверсионируемых или незамороженных источников.

Пути в `relative_path` должны быть относительными, использовать POSIX separators и не содержать traversal.

Core передает adapter-у target block как `dict`, потому что core не должен знать все plugin-specific поля. Adapter обязан вернуть lock-ready dict, который:

- serializable;
- concrete;
- без секретов;
- с тем же `type`;
- валидируется самим adapter-ом.

Target operations имеют side effects. Поэтому dry-run, порядок публикации и manifest-last policy остаются под управлением core. `TargetAdapter` не пишет manifest и не принимает решение о завершенности публикации.

`TargetContext` создает core перед вызовом adapter-а. Plugin не создает context сам и не получает прямой доступ к `PluginManager`.

Минимальный состав `TargetContext`:

```python
class TargetContext:
    plugin_id: str
    target_type: str
    operation: str
    auth: AuthService | None
    logger: PluginLogger
```

Поля:

- `plugin_id` - plugin, который зарегистрировал текущую target capability;
- `target_type` - значение `type` из target ref, например `local`, `svn`, `git`;
- `operation` - текущая операция adapter-а, например `validate_config`, `resolve_lock_ref`, `ensure_root`, `write_file`;
- `auth` - controlled access к будущей системе аутентификации через `AuthService`;
- `logger` - controlled logger для plugin-а; сообщения должны проходить через redaction/secret masking.

В будущем в `TargetContext` можно добавить cache/temp dirs, network settings, cancellation token и dry-run hint. Даже если `dry_run` будет передан в context, решение не писать файлы в dry-run должно оставаться в core: core не должен вызывать side-effect методы при dry-run, если операция не нужна для preview.

## Future: ConfigAdapter

Переработка системы конфигов выносится в отдельный будущий этап проектирования. В ближайшую реализацию plugin foundation `ConfigAdapter` не входит.

Текущее направление мысли:

- config plugin регистрирует config scheme, например `catalog` или `calculation_toml`;
- scheme может быть применима к разным purposes, например `build`, `run`, `publish`;
- пользователь или внешний интерфейс выбирает scheme для нужного purpose;
- adapter возвращает ядру стабильный config bundle / словарь в формате, который core может валидировать и превратить в lock;
- lock-файлы по-прежнему создает только core.

Если config scheme требует взаимодействия с пользователем, adapter не должен открывать окна или зависеть от PyQt/web/CLI. Он должен возвращать абстрактные interaction requests, а конкретный интерфейс будет отображать их пользователю и возвращать ответы.

Пример будущего flow для каталога:

```text
UI/API выбирает scheme "catalog" для build
  -> CatalogConfigAdapter запрашивает путь/источник каталога через InteractionRequest
  -> adapter читает каталог через публичный source service
  -> adapter возвращает InteractionRequest с выбором расчетного кода, версии и rule set
  -> UI/API возвращает ответы
  -> adapter собирает build config bundle
  -> core валидирует bundle и создает build.lock.toml
```

Детальный контракт `ConfigAdapter`, `InteractionRequest`, `InteractionResponse` и config bundle будет спроектирован отдельно.

## ReportAdapter

`ReportAdapter` отвечает за создание пользовательского представления по manifest data: HTML, Markdown, JSON summary, таблица для UI и другие форматы.

`ReportAdapter` работает read-only относительно проекта:

- не меняет manifest;
- не меняет lock-файлы;
- не запускает build/run/publish;
- не вызывает source/target adapters;
- не пишет файлы сам.

Основной flow:

```text
core reads manifest.json
  -> ReportRegistry finds report adapter
  -> ReportAdapter.render()
  -> ReportResult
  -> core/app saves report content to controlled reports directory
```

Обязательный интерфейс:

```python
class ReportAdapter:
    def describe(self, context: ReportContext) -> ReportDescriptor:
        ...

    def render(
        self,
        manifest: dict,
        request: ReportRequest,
        context: ReportContext,
    ) -> ReportResult:
        ...
```

`describe()` возвращает metadata отчета, чтобы UI/API мог показать доступные отчеты без их генерации.

```python
class ReportDescriptor:
    id: str
    title: str
    description: str
    output_formats: list[str]
```

`ReportRequest` задает формат и plugin-specific options:

```python
class ReportRequest:
    report_id: str
    output_format: str
    options: dict
```

`ReportResult` возвращает content. Adapter не выбирает путь записи.

```python
class ReportResult:
    output_format: str
    suggested_filename: str
    content: str | bytes | dict
    warnings: list[str]
```

`ReportContext`:

```python
class ReportContext:
    plugin_id: str
    report_id: str
    logger: PluginLogger
```

Core/app отвечает за сохранение результата в контролируемую директорию отчетов, например `job/.calcchain/reports/`. Это защищает manifest, lock-файлы и другие служебные артефакты от случайной перезаписи report plugin-ом.

## Future: RunnerAdapter

Runner plugins переносятся на отдельный будущий этап проектирования. Пока не фиксируем их обязательный интерфейс и не включаем `RunnerRegistrar` в текущий `PluginContext`.

Открытые вопросы:

- как runner должен описывать среду запуска;
- как передавать файлы/пути между host и runner environment;
- как собирать stdout/stderr/stdin logs;
- как обрабатывать timeout/cancel;
- как формировать post-run snapshot;
- как Docker/remote/cluster runners должны возвращать данные, совместимые с manifest.

До отдельного проектирования текущий `ProcessRunner` остается core-функциональностью.

## AuthAdapter

`AuthAdapter` отвечает за получение credentials по конкретной auth scheme. Source/target adapters не должны сами читать пароли из файлов, переменных окружения, credential store или UI. Они должны запрашивать credentials через `context.auth`, а core направляет запрос в подходящий `AuthAdapter`.

`context.auth` является `AuthService`, а не прямым registry. Source/target adapter вызывает:

```python
credentials = context.auth.get_credentials(requirement)
```

`AuthService` внутри:

```text
validate requirement
  -> check session cache
  -> check persistent store if policy allows
  -> find AuthAdapter
  -> get credentials
  -> apply credential persistence policy
  -> return AuthCredentials
```

Основной flow:

```text
source/target adapter
  -> context.auth.get_credentials(requirement)
  -> AuthService/AuthRegistry selects AuthAdapter
  -> AuthAdapter.validate_requirement()
  -> AuthAdapter.get_credentials()
  -> source/target adapter получает AuthCredentials
```

Пример auth requirement:

```json
{
    "scheme": "username_password",
    "scope": {
        "source_type": "svn",
        "location": "https://svn.example.org/repo"
    },
    "fields": [
        {"name": "username", "secret": false},
        {"name": "password", "secret": true}
    ],
    "persistence": "allowed",
    "optional": false
}
```

Минимальная модель:

```python
class AuthRequirement:
    scheme: str
    scope: dict
    fields: list[AuthField]
    persistence: Literal["forbidden", "allowed"]
    optional: bool = False

class AuthField:
    name: str
    secret: bool
```

Обязательный интерфейс:

```python
class AuthAdapter:
    def can_handle(self, requirement: AuthRequirement, context: AuthContext) -> bool:
        ...

    def validate_requirement(self, requirement: AuthRequirement, context: AuthContext) -> None:
        ...

    def get_credentials(self, requirement: AuthRequirement, context: AuthContext) -> AuthCredentials:
        ...
```

`can_handle()` нужен, потому что несколько auth adapters могут поддерживать одну scheme в разных средах: UI, env, CI или другой approved provider.

`validate_requirement()` проверяет, что auth requirement имеет корректную структуру для данной scheme: ожидаемые поля, scope, optional/required режим.

`get_credentials()` возвращает credentials для текущего запроса. Источник credentials зависит от adapter-а: UI callback, env vars, CI secret provider или другой approved mechanism.

Очистка session/persistent credentials относится к `AuthService` и внутреннему `CredentialStore`, а не к `AuthAdapter`.

`AuthCredentials` должен быть runtime-only объектом. Его нельзя сериализовать в `build.toml`, lock-файлы, manifest, логи или reports.

Минимальная форма:

```python
class AuthCredentials:
    values: dict[str, AuthValue]

class AuthValue:
    value: str
    secret: bool

    def reveal(self) -> str:
        ...
```

`AuthValue` должен быть устроен так, чтобы случайное `str()` / `repr()` не раскрывали секрет. Реальное значение раскрывается только явным вызовом `reveal()` в момент передачи credentials клиенту источника или target-а.

`AuthContext` создает core перед вызовом auth adapter-а.

Минимальный состав `AuthContext`:

```python
class AuthContext:
    plugin_id: str
    auth_provider_id: str
    auth_scheme: str
    operation: str
    logger: PluginLogger
```

Поля:

- `plugin_id` - plugin, который зарегистрировал текущую auth capability;
- `auth_provider_id` - id auth provider-а в `AuthRegistrar`, например `env` или `interactive_prompt`;
- `auth_scheme` - auth scheme, например `username_password`, `token`, `env`;
- `operation` - текущая auth operation, например `validate_requirement`, `get_credentials`;
- `logger` - controlled logger; сообщения должны проходить через redaction/secret masking.

Auth requirements могут объявляться source/target adapter-ами, потому что именно они знают протокол конкретного источника или target. AuthAdapter отвечает только за способ получения credentials.

Source/target adapter владеет тем, как применить credentials к своему клиенту. AuthAdapter владеет только способом получения credentials.

Auth adapters не обязаны быть привязаны к конкретному source/target adapter-у. Например одна scheme `username_password` может использоваться SVN, Git и другими adapters.

Auth errors должны быть частью публичного plugin API и не раскрывать секреты:

- `AuthRequiredError`;
- `AuthCancelledError`;
- `AuthRejectedError`;
- `AuthSchemeUnsupportedError`;
- `AuthStorageError`.

## Credential persistence

`CredentialStore` пока не выносится в plugin API как отдельная capability. Хранение credentials является внутренним слоем auth-системы core/app.

Решение сохранять credentials или нет должно приниматься auth layer, а не source/target adapter-ом.

Решение складывается из трех уровней:

1. Auth requirement от source/target adapter-а.
2. Глобальная credential policy приложения.
3. Выбор пользователя, если policy требует подтверждения.

Модель `AuthRequirement` используется та же, что в разделе `AuthAdapter`: `scheme`, `scope`, `fields`, `persistence`, `optional`.

Минимальная форма глобальной политики:

```python
class CredentialPolicy:
    persistence: Literal["never", "ask", "always"]
```

Persistent save разрешен только если:

```text
requirement.persistence == "allowed"
and policy.persistence != "never"
and пользователь разрешил сохранение при policy.persistence == "ask"
```

Если persistent save не выполняется, credentials можно сохранить только в session memory cache до завершения приложения.

Auth flow:

```text
AuthService.get_credentials()
  -> проверить session memory cache
  -> проверить persistent store, если policy разрешает
  -> если credentials не найдены, выбрать AuthAdapter и запросить credentials у пользователя/окружения
  -> сохранить persistent только если это разрешено requirement, policy и пользователем
  -> иначе сохранить максимум в session memory cache
```

Persistent store backend выбирает core/app: OS credential store, encrypted app store или другой approved mechanism. Source/target adapters не должны сами выбирать место хранения credentials.

Секреты не должны попадать в:

- пользовательские config-файлы;
- lock-файлы;
- manifest;
- логи;
- reports;
- exception messages.

URL-based source/target adapters должны отклонять userinfo в URL для своих протоколов. Credentials должны передаваться только через auth context.
