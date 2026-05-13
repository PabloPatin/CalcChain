1. Source plugins

Источники входных данных, кода и правил:

- svn - первый кандидат на вынос в plugin.
- git - расчётный код и правила из Git repo/tag/commit.
- s3 / minio - входные наборы и опубликованные артефакты.
- http / https readonly source - скачать архив или отдельные файлы.
- zip/tar archive source - использовать архив как файловое дерево.
- database source - выгрузить входные данные из БД в файлы.
- artifact repository source - Nexus/Artifactory/internal storage.

local я бы оставил в core, как ты и предложил.

2. Target plugins

Куда публиковать результаты:

- svn target.
- git target, если результаты надо коммитить.
- s3/minio target.
- filesystem archive target - публикация в zip/tar с manifest внутри.
- http api target - отправка результата во внутренний сервис.
- database target - запись метаданных и ссылок на файлы.

3. Catalog plugins

Каталоги не только расчётных кодов:

- каталог расчётных кодов;
- каталог наборов входных файлов;
- каталог benchmark/test cases;
- каталог run presets;
- каталог output publication profiles;
- корпоративный каталог, который берёт данные из SVN/Git/БД/API.

Здесь важно: каталог помогает выбрать и собрать lock, но после lock не
должен быть источником воспроизводимости.

4. Auth plugins

Разные способы получения credentials:

- interactive callback;
- env vars;
- .netrc;
- Windows Credential Manager;
- Linux Secret Service / macOS Keychain;
- corporate token provider;
- SSH agent;
- Kerberos/SSO;
- CI secrets provider.

Auth plugin лучше держать отдельно от source/target plugin, но source/
target plugin должен уметь объявлять, какие auth-схемы он поддерживает.

5. Config transform plugins

Преобразование пользовательских сценариев в текущие форматы:

- calculation.toml -> build.toml/run.toml/publish.toml;
- wizard/GUI draft -> lock;
- legacy config.toml -> новый core format;
- шаблоны расчётов;
- batch generation для серии расчётов.

Это хороший слой для будущего единого calculation.toml.

6. Rules plugins

Сейчас правила regex-based. В будущем могут понадобиться:

- другой rule engine;
- rules из Python-функций;
- rules из YAML/TOML;
- domain-specific rules для конкретных расчётных кодов;
- output classifier plugin, если простых file rules недостаточно;
- validator правил для конкретного solver-а.

Но я бы осторожно расширял эту область: правила напрямую влияют на
воспроизводимость.

7. Runner plugins

Запуск расчёта в разных средах:

- local process runner, текущий базовый;
- Docker/Podman runner;
- Singularity/Apptainer runner;
- SLURM/PBS/LSF cluster runner;
- remote SSH runner;
- Windows-specific console runner;
- WSL runner.

Это крупное направление, потому что runner влияет на env, paths, logs,
timeout/cancel и manifest.

8. Integrity / policy plugins

Оценка воспроизводимости и публикационной политики:

- corporate reproducibility policy;
- “можно публиковать только если все inputs versioned/frozen”;
- запрет unknown outputs;
- проверка подписи manifest;
- проверка trusted source locations;
- compliance/audit report.

Лучше делать это отдельным policy layer, а не смешивать с build/run/
publish.

9. Report plugins

Разные отчёты поверх manifest:

- HTML report;
- Markdown report;
- PDF report;
- machine-readable audit JSON;
- comparison report между двумя расчётами;
- provenance graph;
- DFD/lineage export.

Это безопасное направление: plugin читает manifest и не влияет на расчёт.

10. UI / assistant plugins

Вспомогательные интерфейсы:

- CLI commands plugin;
- GUI panels для каталога;
- wizard создания build.toml;
- интерактивный выбор run preset;
- preview/dry-run viewer.