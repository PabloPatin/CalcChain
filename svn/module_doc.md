## class SvnClient(url, \*, username=None, password=None, svn_filepath='svn', trust_cert=False, env=None, check_exists=True)

Класс SvnClient предназначен для выполнения команд SVN при помощи обращения к
утилите [SVN CLI](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.html) с использованием различных параметров. Он
позволяет вызывать методы для работы с SVN CLI без необходимости иметь рабочую копию репозитория.

* `url`: Ссылка на репозиторий или папку в нём.
* `username` и `password`: Имя пользователя и пароль для аутентификации при работе с репозиторием. Если не указаны,
  аутентификация не будет выполняться.
* `svn_filepath`: Путь к исполняемому файлу утилиты SVN CLI. Если не указан, по умолчанию используется файл `svn` в
  директории PATH.
* `trust_cert`: Флаг, указывающий, следует ли доверять сертификату сервера. Если True, сертификат не будет проверяться.
* `env`: Словарь переменных среды для SVN CLI.
* `check_exists`: Флаг, указывающий, следует ли проверять возможность подключения по указанному url. Если True, путь
  будет проверен перед выполнением команд.
* `encoding`: Кодировка, которая используется для чтения и записи коммитов (если не указана в методе). 
  По умолчанию `cp1251`.

```python3
>>> client = SvnClient('svn://example/repo')
# Создание объекта SvnClient для репозитория по адресу svn://example/repo
>>> client = SvnClient('svn://example/repo/folder', check_exists=True)
# Создание объекта SvnClient для сущесивующей папки в репозитории по адресу svn://example/repo/folder
>>> client = SvnClient('svn://example/repo', username='login', password='password')
# Создание объекта SvnClient для репозитория с логином и паролем
```

## Вызываемые исключения

### class SvnError(Exception)

Исключение, которое будет вызвано, если при работе с утилитой SVN CLI команда завершилась с ненулевым кодом ошибки.

Объект исключения имеет следующие атрибуты:

* `cmd`: Команда svn CLI, которая вызвала исключение.
* `return_code`: Код возврата утилиты svn CLI.
* `stdout`: Выходные данные утилиты svn CLI.
* `stderr`: Ошибочные выходные данные утилиты svn CLI. None, если ошибок нет.
* `url`: Url, который был передан в качестве аргумента.
* `error_codes`: Коды ошибок svn, возникших при попытке выполнения команды

## Атрибуты и методы

### SvnClient.url

url, который в данный момент используется в качестве корня для всех методов, имплементирующих запросы к репозиторию.

```python3
>>> client.url
'svn://example/repo'
```

### SvnClient.set_url(self, url, \*, check_exists=False)

Метод `set_url` устанавливает новую ссылку на репозиторий или папку в нём.

* `url`: Ссылка на репозиторий или папку в нём.
* `check_exists`: Флаг, указывающий, следует ли проверять возможность подключения по указанной ссылке. Если True,
  будет проверено подключение перед установкой ссылки.

```python3
>>> client.set_url('svn://example/new-repo')
>>> client.url
'svn://example/new-repo'
```

### SvnClient.run_command(self, subcommand, \*args, split_lines=False, return_binary=False, encoding=None, wd=None, join_stderr=False) -> str | list\[str\] | bytes

Метод `run_command` запускает команду SVN CLI и возвращает её stdout.

* `subcommand`: Команда для утилиты SVN.
* `args`: Список аргументов для команды.
* `split_lines`: Флаг, указывающий, следует ли поделить вывод на строки. Если True, вывод будет разделен на отдельные
  строки.
* `return_binary`: Флаг, указывающий, следует ли вернуть вывод в бинарном виде. Если True, вывод будет возвращен как
  объект bytes.
* `encoding`: Указать кодировку для текста. Если не указан, по умолчанию используется cp1251 (Windows).
* `wd`: Путь, из которого будет вызвана команда. Если не указан, команда будет вызвана из текущей директории.
* `join_stderr`: Флаг, указывающий, следует ли перенаправить stderr в stdout. Если True, stderr будет перенаправлен в
  stdout.

метод возвращает вывод команды SVN CLI в виде строки, списка строк (если split_lines=True), либо байтов (если
return_binary=True).

```python3
>>> output = client.run_command('info')
# Вызов команды info и возврат вывода
>>> output = client.run_command('list', split_lines=True)
# Вызов команды list с разделением вывода на строки
>>> output = client.run_command('status', return_binary=True)
# Вызов команды status с возвращением вывода в бинарном виде
```

### SvnClient.info(self, path=None, \*, revision=None) -> Info

Метод является обёрткой команды [info](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.c.info.html) и возвращает
информацию о репозитории или любом объекте в нём.

* `path`: Путь к папке в репозитории относительно SvnClient.url. Если не указан, информация будет получена для
  SvnClient.url.
* `revision`: Номер ревизии, для которой будет получена информация. Если не указан, информация будет получена для
  текущей ревизии.

Метод возвращает именованный кортеж `Info`, содержащий следующие значения:

- `xml`: XML-описание репозитория или папки.
- `url`: Полная ссылка на репозиторий или папку.
- `relative_url`: Ссылка на репозиторий или папку относительно корня.
- `entry_kind`: Тип записи в репозитории (например, файл, директория и т.п.).
- `entry_path`: Путь к записи в репозитории.
- `entry_revision`: Номер ревизии записи в репозитории.
- `repository_root`: Ссылка на корневую папку репозитория.
- `repository_uuid`: Уникальный идентификатор репозитория.
- `commit_author`: Автор последнего коммита к записи в репозитории (если доступно).
- `commit_date`: Дата последнего коммита к записи в репозитории.
- `commit_revision`: Номер ревизии последнего коммита к записи в репозитории.

```python3
>>> client = SvnClient('svn://example/repo/content_folder')
>>> info = client.info()
# Получение информации о папке content_folder головной ревизии
>>> info = client.info(path='some_file.txt', revision=123)
# Получение информации о файле 'content_folder/some_file' в репозитории 123 ревизии
>>> info.relative_url
'^/content_folder/some_file'
```

### SvnClient.cat(self, filepath, \*, revision=None, encoding=None, return_binary=False) -> str | bytes

Метод является обёрткой команды [cat](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.c.cat.html) и возвращает
содержимое файла в репозитории.

* `filepath`: Путь к файлу или папке в репозитории относительно SvnClient.url.
* `revision`: Номер ревизии, для которой будет получено содержимое. Если не указан, содержимое будет получено для
  текущей ревизии.
* `encoding`: Кодировка файла (например, 'utf-8', 'latin1' и т.п.). Если не указана, содержимое будет возвращено в
  кодировке по умолчанию (cp1251).
* `return_binary`: Флаг, указывающий, что содержимое должно быть возвращено как байты.

Метод возвращает строку или байты, содержимое файла или папки в репозитории.

```python3
>>> client = SvnClient('svn://example/repo/content_folder')
>>> client.cat('some_file.txt')
'file content'
>>> content = client.cat('some_file.txt', return_binary=True)
b'file content'
```

### SvnClient.log(self, path=None, \*, stop_on_copy=False, limit=None, revision=None, from_revision=None, to_revision=None, from_datetime=None, to_datetime=None, changelist=False) -> tuple\[LogRecord\]

Метод является обёрткой команды [log](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.c.log.html) и возвращает
историю изменений файла или папки в репозитории.

* `stop_on_copy`: Устанавливает флаг [
  `--stop-on-copy`](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.html#svn.ref.svn.sw.stop_on_copy).
* `limit`: Максимальное количество записей в истории изменений.
* `from_revision` и `to_revision`: Диапазон ревизий, для которых будет получена история изменений.
* `from_datetime` и `to_datetime`: Диапазон дат, для которых будет получена история изменений в
  формате [datetime](https://docs.python.org/3/library/datetime.html).
* `changelist`: Флаг, указывающий, что необходимо так же извлечь все пути, затронутые изменениями и сообщения коммитов.

Метод возвращает кортеж из `LogRecord` объектов, каждый из которых представляет собой запись истории изменений. Каждая
запись содержит следующие поля:

* `xml`: XML-описание записи.
* `revision`: Номер ревизии, к которой относится запись.
* `author`: Автор коммита.
* `date`: Дата коммита в формате [datetime](https://docs.python.org/3/library/datetime.html).
* `msg`: Сообщение коммита. None, если changelist=False.
* `paths`: кортеж из LogPath объектов, каждый из которых представляет собой изменение в файле или папке. None, если
  changelist=False.

Каждый `LogPath` объект содержит следующие поля:

* `prop_mods`: Флаг, указывающий, что были изменения свойств.
* `text_mods`: Флаг, указывающий, что было изменено содержимое файла.
* `kind`: Тип изменяемого объекта ('dir' или 'file').
* `action`: Действие, произведенная над файлом или папкой.
    * Action.ADD - Добавление.

    - Action.MODIFY - Изменение.
    - Action.DELETE - Удаление.
* `path`: Путь к файлу или папке.

```python3
>>> client = SvnClient('svn://example/repo/content_folder')
>>> log_records = client.log()
# Получение истории изменений корневой папки репозитория
>>> log_record = log_records[0]
# Получение первого LogRecord объекта из истории изменений
>>> log_record.revision  # Номер ревизии
123
>>> log_record.author  # Автор коммита
'user'
>>> log_record.date  # Дата коммита
datetime.datetime(1970, 1, 1, 3, 0)
>>> log_object = log.path[0]
# Получение первого LogPath объекта
>>> log_object.kind
'file'
>>> log_object.path  # Путь изменяемого объекта       
'some_file.txt'
```

### SvnClient.export(self, from_path, to_path, \*, revision=None, force=False, depth=Depth.INFINITY)

Метод является обёрткой команды [export](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.c.export.html) и
экспортирует файлы и папки из репозитория в указанный путь.

* `from_path`: Путь к файлу или папке в репозитории для экспорта. None, если экспортировать папку SvnClient.url.
* `to_path`: Путь, куда будет сохранено содержимое репозитория.
* `force`: Флаг, указывающий, что необходимо перезаписывать файлы, которые уже существуют в целевой папке.
* `depth`: Глубина экспорта.
    * Depth.INFINITY - экспорт всех файлов и подпапок.
    * Depth.IMMEDIATES - экспорт только объектов непосредственно лежащих в указанной папке.
    * Depth.FILES - экспорт только файлов из папки.
    * Depth.EMPTY - экспорт файла или пустой папки.

```python3
>>> client = SvnClient('svn://example/repo/content_folder')
# Создание экземпляра клиента для репозитория 'content_folder'
>>> client.export(to_path='/path/to/export')
# Экспорт папки 'content_folder' в '/path/to/export' со всем содержимым
>>> client.export(from_path='some_file.txt', to_path='/path/to/export')
# Экспорт файла 'some_file.txt' в '/path/to/export'
```

### SvnClient.import_(self, from_path, to_path, message='', \*, force=False, encoding='utf-8', depth=Depth.INFINITY)

Метод является обёрткой команды [import](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.c.import.html) и
импортирует файлы из указанного пути в репозиторий.

* `from_path`: Путь к файлу или папке, содержимое которых необходимо импортировать.
* `to_path`: Путь к папке в репозитории, куда будет импортировано содержимое файла или папки.
* `message`: Сообщение коммита.
* `encoding`: Кодировка сообщения коммита.

```python3
>>> client = SvnClient('svn://example/repo/content_folder')
# Создание экземпляра клиента для репозитория 'content_folder'
>>> client.import_(from_path='/path/to/import', to_path='some_file.txt')
# Импорт файла '/path/to/import' в папку 'content_folder/some_file.txt'
>>> client.import_(from_path='/path/to/import', to_path='new_folder',
                    message='Импорт папки без подпапок', depth=Depth.FILES)
# Импорт с сообщением коммита
```

### SvnClient.mkdir(self, path=None, message='', \*, parents=False, encoding='utf-8', exist_ok=False)

Метод является обёрткой команды [mkdir](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.c.mkdir.html) и создаёт
новую папку в репозитории.

* `path`: Путь к папке, которую необходимо создать. None, если создавать папку SvnClient.url.
* `message`: Сообщение коммита.
* `parents`: Флаг, указывающий, что необходимо создавать родительские папки, если они не существуют.
* `exist_ok`: Флаг, указывающий, что необходимо игнорировать ошибку, если папка уже существует.

```python3
>>> client = SvnClient('svn://example/repo/content_folder')
>>> client.mkdir(message='Создание папки content_folder', exist_ok=True)
# Ничего не произойдёт, если папка уже существует
>>> client.mkdir('parent/new_folder', message='Создание папки new_folder', parents=True)
# Создание родительских папок
```

### SvnClient.delete(self, path=None, message='', \*, force=False)

Метод является обёрткой команды [delete](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.c.delete.html) и удаляет
файл или папку из репозитория.

* `path`: Путь к файлу или папке, которое необходимо удалить. None, если удалить файл или папку SvnClient.url.
* `message`: Сообщение коммита.
* `force`: Флаг, указывающий, что необходимо принудительно удалить папку, даже если она не пустая.

```python3
>>> client = SvnClient('svn://example/repo/content_folder')
# Создание экземпляра клиента для репозитория 'content_folder'
>>> client.delete(path='file.txt')  # Удаление файла 'file.txt' в 'content_folder'
>>> client.delete(message='Удаление папки с содержимым', force=True)
# Принудительное удаление папки content_folder
```

### SvnClient.list(self, path=None, \*, recursive=False, revision=None) -> StorageTree

Метод является обёрткой команды [ls](https://svnbook.red-bean.com/nightly/en/svn.ref.svn.c.list.html) и возвращает
содержимое указанной папки.

* `path`: Путь к папке, которую необходимо просмотреть. None, если просмотреть папку SvnClient.url.
* `recursive`: Флаг, указывающий, что необходимо включать в вывод подпапки.

Метод возвращает объект класса `StorageTree`, который представляет собой корневую папку. Он содержит следующие поля:

* `xml`: XML-описание дерева.
* `root`: Путь к корню.
* `nodes`: Кортеж из объектов класса `StorageNode`, каждый из которых представляет собой файл или папку.

Каждый `StorageNode` объект содержит следующие поля:

* `xml`: XML-описание узла.
* `path`: Путь к узлу относительно корневого пути.
* `kind`: Тип узла ('file' или 'dir').
* `name`: Имя файла или папки.
* `size`: Размер файла в байтах. None, если узел является папкой.
* `revision`: Номер ревизии, к которой относится узел.
* `author`: Автор последнего коммита, затронувшего узел.
* `date`: Дата последнего коммита, затронувшего узел в
  формате [datetime](https://docs.python.org/3/library/datetime.html).

```python3
>>> client = SvnClient('svn://example/repo/content_folder')
# Создание экземпляра клиента для папки 'content_folder' в репозитории
>>> content = client.list(recursive=True)  # Просмотр всех объектов рекурсивно
>>> paths = [node.rel_path for node in content.nodes if node.kind == 'file']
# Получение списка путей файлов
>>> '\n'.join(paths)
'some_file.dat'
'subfolder/file.txt'
'subfolder/some_folder/other_file.txt'

>>> content = client.list(path='subfolder')  # Просмотр подпапки 'subfolder'
>>> paths = [node.rel_path for node in content.nodes]
>>> '\n'.join(paths)
'subfolder/file.txt'
'subfolder/some_folder'
# Только объекты, находящиеся непосредственно в 'subfolder'
```