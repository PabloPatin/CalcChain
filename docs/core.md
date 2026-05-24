# CalcChain Core

Этот документ фиксирует текущий вариант `calcchain_core` после переноса нового ядра на место старого и отделения plugin-specific логики в `calcchain_plugin_system`.

## Назначение

`calcchain_core` - ядро расчетного lifecycle одного job directory.

Ядро отвечает за:

- чтение и запись core-конфигов;
- build lock, build plan и материализацию рабочей директории;
- запуск процесса;
- snapshots, file maps, frozen inputs и manifest;
- классификацию выходных файлов;
- publish, restore и cleanup;
- встроенный local source/target;
- runtime-интерфейсы capabilities;
- разрешение секретов через `SecretsResolver`.

Ядро не отвечает за:

- поиск, установку, импорт и активацию плагинов;
- чтение `plugin.json`;
- проверку plugin dependencies;
- plugin environment;
- plugin lifecycle.

Эта логика относится к `calcchain_plugin_system`.

## Граница с Plugin System

`calcchain_core` не должен импортировать `calcchain_plugin_system`.

`calcchain_plugin_system` может импортировать core-интерфейсы и собирать объект:

```python
RuntimeCapabilities(
    active_owner_ids=(...),
    capabilities={
        CapabilityKey("source", "..."): CapabilityRecord(...),
        CapabilityKey("target", "..."): CapabilityRecord(...),
        CapabilityKey("report", "..."): CapabilityRecord(...),
        CapabilityKey("secrets", "..."): CapabilityRecord(...),
    },
)
```

Затем runtime передается в ядро:

```python
core = CalculationCore(job_dir, runtime=runtime)
```

Плагины регистрируют capabilities не напрямую в core registry, а через `PluginContext` из `calcchain_plugin_system`.

## Публичная точка входа

Главный фасад:

```python
from calcchain_core import CalculationCore
```

`CalculationCore` принимает:

- `job_dir`;
- `runtime`;
- готовые `source_registry`, `target_registry`, `report_registry`, если нужно подменить registry;
- готовый `secrets_resolver`, если нужно полностью подменить систему секретов;
- `secret_policy`;
- `secret_store`.

Если `secrets_resolver` не передан, ядро строит `RuntimeSecretsResolver` из `runtime`.

## Структура пакета

Текущие доменные зоны:

```text
calcchain_core/
  build/          build config, lock, plan, builder
  capabilities/   runtime capability contracts and adapter protocols
  cleanup/        cleanup work dir
  common/         common errors, hashes, statuses
  io/             refs, source registry, target registry
  manifest/       manifest model and writer
  publish/        publish config, lock, plan execution
  reports/        report value objects and registry
  restore/        restore from manifest
  rules/          rules config and mapping
  run/            run config, runner, frozen inputs, pre-run preparation
  secrets/        resolver, persistence policy, stores
  utils/          TOML/JSON/file helpers and validation
  workspace/      layout, snapshots, maps, artifacts, output classifier
```

Старые корневые модули вроде `api.py`, `models/`, `config/`, `io/auth.py`, `io/sources.py`, `io/targets.py` больше не являются частью нового ядра.

## Capabilities

Core определяет общий runtime-формат в `calcchain_core.capabilities`.

Основные value objects:

- `CapabilityKey(namespace, id)`;
- `CapabilityOwner(id, version=None, metadata={})`;
- `CapabilityRecord(key, adapter, owner=None, metadata={})`;
- `RuntimeCapabilities(capabilities, active_owner_ids, environment, diagnostics)`;
- `ResolvedCredentials(public, secrets)`.

Поддерживаемые namespaces:

- `source`;
- `target`;
- `report`;
- `secrets`.

## Adapter Protocols

Все adapter protocols находятся в:

```python
calcchain_core.capabilities.adapters
```

Экспортируются также через:

```python
from calcchain_core.capabilities import SourceAdapter, TargetAdapter, ReportAdapter, SecretsAdapter
```

### SourceAdapter

```python
class SourceAdapter(Protocol):
    def validate_config(self, ref, context) -> None: ...
    def resolve_lock_ref(self, ref, context) -> dict: ...
    def validate_lock_ref(self, ref, context) -> None: ...
    def list_files(self, ref, context) -> list[str]: ...
    def read_file(self, ref, relative_path, context) -> bytes: ...
    def is_versionable(self, ref, context) -> bool: ...
```

### TargetAdapter

```python
class TargetAdapter(Protocol):
    def validate_config(self, ref, context) -> None: ...
    def resolve_lock_ref(self, ref, context) -> dict: ...
    def validate_lock_ref(self, ref, context) -> None: ...
    def ensure_root(self, ref, context) -> dict: ...
    def write_file(self, ref, relative_path, data, context) -> Mapping: ...
    def is_versionable(self, ref, context) -> bool: ...
```

### ReportAdapter

```python
class ReportAdapter(Protocol):
    def describe(self, context) -> ReportDescriptor: ...
    def render(self, request, context) -> ReportResult: ...
```

### SecretsAdapter

```python
class SecretsAdapter(Protocol):
    def can_resolve(self, key: str, context: SecretsContext) -> bool: ...
    def resolve(self, key: str, context: SecretsContext) -> str: ...
```

`SecretsAdapter` является capability, но сам `SecretsResolver` принадлежит core.

## Source и Target Refs

Source и target refs используют общий объект:

```python
ExternalRef(data: dict, credentials: RefCredentials | None)
```

Алиасы:

```python
SourceRef = ExternalRef
TargetRef = ExternalRef
SourceCredentials = RefCredentials
TargetCredentials = RefCredentials
```

`ExternalRef.data` не интерпретируется ядром сверх обязательного поля `type`. Содержимое `data` является ответственностью конкретного adapter-а.

Credentials имеют формат:

```toml
[inputs.source.credentials.public]
username = "calcchain_user"

[inputs.source.credentials.secrets]
password = "svn_calc_data_password"
```

`public` содержит явные значения.

`secrets` содержит ключи для secret storage или значение `@auto`.

## Registries

`SourceRegistry` и `TargetRegistry` находятся в `calcchain_core.io`.

Встроенные capabilities:

- `source:local`;
- `target:local`.

Они регистрируются самим core при создании registry. Plugin capabilities приходят через `RuntimeCapabilities`:

```python
SourceRegistry.from_runtime(runtime, secrets_resolver=...)
TargetRegistry.from_runtime(runtime, secrets_resolver=...)
ReportRegistry.from_runtime(runtime)
```

Plugin capability не регистрируется напрямую в core registry. Это сохраняет границу: plugin discovery и activation остаются в `calcchain_plugin_system`.

## Secrets

Система секретов состоит из:

- `SecretsResolver`;
- `RuntimeSecretsResolver`;
- `SecretsAdapter`;
- `SecretPersistencePolicy`;
- `MemorySecretStore`;
- `KeyringSecretStore`.

Namespace capability:

```python
CapabilityKey("secrets", "...")
```

Плагин может зарегистрировать secrets capability через `context.secrets.register(...)` в `calcchain_plugin_system`.

Core получает эти capabilities через `RuntimeCapabilities` и строит `RuntimeSecretsResolver`.

### Resolve Flow

`RuntimeSecretsResolver.resolve(key, context=...)` работает так:

1. Вычисляет storage key.
2. Если storage key есть, сначала смотрит memory cache, если policy разрешает memory.
3. Затем смотрит persistent store, если policy разрешает store.
4. Если значение найдено, capability не вызывается.
5. Если значения нет или storage key не передан, вызывает подходящий `SecretsAdapter`.
6. После успешного получения сохраняет секрет согласно policy.

### Storage Key

Если key пустой или `None`, storage не используется.

Если key обычная строка, она используется как storage key.

Если key равен:

```python
@auto
```

то ядро генерирует стабильный key по hash от request context.

Для source/target credentials в request context попадает `ref.data`. Ядро не интерпретирует этот ref, а только использует его как часть материала для стабильного auto-key.

### Persistence Policy

```python
SecretPersistencePolicy(
    allow_memory=True,
    allow_store=True,
)
```

Правила:

- `allow_memory=True` - читать и писать `MemorySecretStore`;
- `allow_store=True` - читать и писать persistent store;
- если включены оба, порядок чтения: memory -> persistent store -> capability;
- если включена только memory, persistent store не трогается;
- если оба выключены, каждый resolve идет в capability без сохранения.

Persistent store по умолчанию:

```python
KeyringSecretStore(service_name="calcchain")
```

`keyring` является зависимостью `calcchain-core`.

## Build Lifecycle

Основные модули:

- `build/config.py`;
- `build/lock.py`;
- `build/plan.py`;
- `build/builder.py`.

Основные шаги:

1. `create_build_lock()` читает `build.toml`.
2. `BuildConfig` парсит структуру.
3. `SourceRegistry.validate_config()` проверяет refs через source adapters.
4. `SourceRegistry.resolve_lock_ref()` создает resolved refs для lock.
5. `BuildLock` записывается в `build.lock.toml`.
6. `validate_build()` строит `BuildPlan`.
7. `build()` материализует source files в workdir.
8. Создаются build artifacts, file maps, snapshot и manifest после build.

`BuildLock` хранит resolved source refs, но `SourceRef.data` все равно не интерпретируется ядром.

## Run Lifecycle

Основные модули:

- `run/config.py`;
- `run/run_preparation.py`;
- `run/frozen_inputs.py`;
- `run/runner.py`.

Перед запуском:

- создается pre-run snapshot;
- фиксируются frozen inputs;
- проверяется готовность workdir.

`ProcessRunner`:

- запускает процесс;
- поддерживает `stdin_mode = "none"` и `stdin_mode = "script"`;
- не поддерживает интерактивный terminal mode;
- resolved secret env получает через `SecretsResolver`;
- маскирует реальные resolved secret values в stdout/stderr.

После запуска:

- создается post-run snapshot;
- output classifier сравнивает pre/post snapshots;
- manifest обновляется результатами run.

## Workspace

`workspace/` содержит данные и операции вокруг job layout:

- `JobLayout`;
- snapshots;
- file maps;
- artifact refs;
- output classifier.

`FileSetMap` хранит связь source files и workdir files. Он нужен там, где одного `BuildPlanEntry` и snapshot недостаточно: manifest, restore, publish и проверка происхождения файлов.

## Manifest

Manifest вынесен в отдельный пакет:

```python
calcchain_core.manifest
```

Manifest создается через typed API `ManifestWriter`.

Цели:

- не передавать нетипизированные dict-like объекты в lifecycle writer;
- избегать двусмысленных fallback-полей;
- фиксировать build/run/publish факты по мере выполнения программы.

Manifest является главным источником фактов для restore.

## Publish

Основные модули:

- `publish/config.py`;
- `publish/lock.py`;
- `publish/publish.py`.

Publish flow:

1. `create_publish_lock()` резолвит target refs через `TargetRegistry`.
2. `build_publish_plan()` читает manifest и rules.
3. `execute_publish_plan()` пишет файлы через target adapters.
4. Target adapter возвращает mapping с опубликованным source ref.
5. Manifest обновляется publication facts.

`PublishLock` не хранит собственный hash внутри себя.

## Restore

Restore находится в:

```python
calcchain_core.restore
```

Текущий режим restore - PRE_RUN.

Restore восстанавливает окружение, каким оно было перед запуском:

- code;
- inputs;
- frozen inputs;
- рабочие файлы, необходимые для воспроизведения pre-run состояния.

Restore читает manifest, а не `build.toml`, `run.toml` или `publish.toml`.

Для frozen inputs restore сначала использует manifest facts и опубликованные service-копии, если они есть. Fallback к source refs поддерживается через `SourceRegistry`, который сам выбирает adapter по `SourceRef`.

## Reports

Reports находятся в:

```python
calcchain_core.reports
```

Плагин регистрирует report capability через `context.reports.register(...)`.

Core строит `ReportRegistry.from_runtime(runtime)`.

Report adapter получает:

- `ReportContext`;
- frozen manifest view;
- `ReportRequest`.

Результат:

- возвращается как `ReportResult`;
- или экспортируется в controlled reports directory, если `request.output == "file"`.

## Rules

Rules находятся в:

```python
calcchain_core.rules
calcchain_core.rules.mapping
```

Mapping основан на старом mapping-модуле, но перенесен внутрь rules.

Rules используются:

- при build mapping;
- при output classification;
- при publish grouping.

## Public Imports

Основные публичные импорты:

```python
from calcchain_core import CalculationCore
from calcchain_core.capabilities import RuntimeCapabilities, SourceAdapter, TargetAdapter, ReportAdapter, SecretsAdapter
from calcchain_core.io import SourceRef, TargetRef, SourceRegistry, TargetRegistry
from calcchain_core.secrets import SecretPersistencePolicy, RuntimeSecretsResolver
from calcchain_core.reports import ReportRequest, ReportResult, ReportDescriptor
from calcchain_core.restore import RestoreRequest
```

Старые импорты не поддерживаются:

```python
calcchain_core.api
calcchain_core.models
calcchain_core.config
calcchain_core.io.auth
calcchain_capabilities
```

## Import Health

Текущий вариант проверен на:

- импорт всех production-модулей `calcchain_core` и `calcchain_plugin_system`;
- изолированный импорт каждого модуля в отдельном Python-процессе;
- проверку всех `__all__` exports;
- public star imports;
- smoke регистрации SVN plugin.

Опасных циклов импортов в текущей структуре не обнаружено.

## Принятые решения

- `calcchain_core` не зависит от `calcchain_plugin_system`.
- `calcchain_capabilities` удален как отдельный пакет.
- Runtime capability contracts принадлежат core.
- Plugin registration flow принадлежит `calcchain_plugin_system`.
- Built-in `local` source/target регистрируются внутри core registry.
- Plugin source/target/report/secrets приходят через `RuntimeCapabilities`.
- `SourceRef` и `TargetRef` объединены через общий `ExternalRef`.
- Core не валидирует внутреннюю структуру `ExternalRef.data` кроме обязательного `type`.
- `auth` заменен на `credentials` и `SecretsResolver`.
- Secrets являются capability, но resolver и persistence policy принадлежат core.
- Секреты маскируются по реальным resolved secret values, а не по эвристическим именам ключей.
- Интерактивный terminal/stdin mode пока не реализуется; остается `none` и `script`.
- Restore сейчас поддерживает PRE_RUN режим.
