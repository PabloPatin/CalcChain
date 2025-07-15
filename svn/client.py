import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path, PurePath
from xml.etree import ElementTree

from .commander import Commander
from .data_structures import Info, LogRecord, LogPath, Action, StorageTree, StorageNode, Depth
from .exception import SvnError

Rev = int | str | None

_LOGGER = logging.getLogger(__name__)


class SvnClient(Commander):
    """Класс SvnClient предназначен для выполнения команд SVN при помощи обращения к утилите
    SVN CLI с использованием различных параметров"""

    def __init__(
            self,
            url: str,
            *,
            username: str | None = None,
            password: str | None = None,
            svn_filepath: str | Path = 'svn',
            trust_cert: bool = False,
            env: dict | None = None,
            check_exists: bool = True,
            encoding: str = 'cp1251',
            ):
        """
        :arg url: Ссылка на репозиторий или папку в нём
        :param username: Имя пользователя (опционально)
        :param password: Пароль (опционально)
        :param svn_filepath: Путь к исполняемому файлу утилиты SVN CLI
                             (указать, если его нет в PATH)
        :param trust_cert: Не проверяет наличие сертификата у сервера если True
        :param env: Переменные среды для SVN CLI
        """
        self._url = None
        self.__username = username
        self.__password = password
        self.__svn_filepath = str(svn_filepath)
        self.__env = env
        self._encoding = encoding
        self._trust_cert = trust_cert
        self.set_url(url, check_exists=check_exists)

    @property
    def url(self):
        return self._url

    def set_url(self, url: str, *, check_exists: bool = False) -> None:
        self._url = self._reformat_link(url)
        if check_exists:
            self.info()

    def _reformat_link(self, url: str) -> str:
        return url.replace('\\', '/')

    def run_command(
            self, subcommand: str,
            *args: str,
            split_lines: bool = False,
            return_binary: bool = False,
            encoding: str | None = 'cp1251',
            wd: str | Path | None = None,
            join_stderr: bool = False,
            ) -> str | Sequence[str] | bytes:
        """Запускает команду SVN CLI и возвращает её вывод

        :arg subcommand: Команда для утилиты SVN
        :arg args: Список аргументов для команды
        :param split_lines: Поделить вывод на
        :param return_binary: Вернуть вывод в бинарном виде
        :param encoding: Указать кодировку для текста
        :param wd: Путь, из которого будет вызвана команда
        :param join_stderr: Перенаправить stderr в stdout
        :return: Результат выполнения команды
        """
        cmd = self._form_cmd(subcommand, *args)
        output = self.external_command(
                cmd,
                environment=self.__env,
                split_lines=split_lines,
                return_binary=return_binary,
                encoding=encoding,
                wd=wd,
                join_stderr=join_stderr,
                )

        if output.return_code != 0:
            stdout = output.stdout.decode() if return_binary else output.stdout
            stderr = output.stderr.decode() if return_binary else output.stderr
            raise SvnError(
                    ' '.join(cmd),
                    return_code=output.return_code,
                    stdout=stdout,
                    stderr=stderr,
                    url=self.url,
                    )

        return output.stdout

    def _form_cmd(self, subcommand: str, *args: str) -> list[str]:
        cmd = [self.__svn_filepath, subcommand, '--non-interactive']
        if self._trust_cert:
            cmd += ['--trust-server-cert']

        if self.__username and self.__password:
            cmd += ['--username', self.__username]
            cmd += ['--password', self.__password]
            cmd += ['--no-auth-cache']

        cmd += list(args)
        return cmd

    def _form_abs_link(self, path: str | PurePath | None, revision: Rev = None) -> str:
        if path in (PurePath(), '.'):
            path = None
        link = f'{self.url}/{PurePath(path).as_posix()}' if path else self.url

        if revision:
            link += f'@{revision}'
        return link

    def info(self, path: str | PurePath = '', *, revision: Rev = None) -> Info:
        full_link = self._form_abs_link(path, revision)
        result = self.run_command('info', '--xml', full_link)
        return self.__parse_info_result(result)

    def __parse_info_result(self, result: str) -> Info:
        root = ElementTree.fromstring(result)
        entry_attr = root.find('entry').attrib
        commit_attr = root.find('entry/commit').attrib
        relative_url = root.find('entry/relative-url')
        author = root.find('entry/commit/author')

        return Info(
                xml=result,
                url=root.find('entry/url').text,
                relative_url=relative_url.text if relative_url is not None else None,
                entry_kind=entry_attr['kind'],
                entry_path=entry_attr['path'],
                entry_revision=int(entry_attr['revision']),
                repository_root=root.find('entry/repository/root').text,
                repository_uuid=root.find('entry/repository/uuid').text,
                commit_author=author.text if author is not None else None,
                commit_date=datetime.fromisoformat(root.find('entry/commit/date').text),
                commit_revision=int(commit_attr['revision']),
                )

    def cat(
            self,
            filepath: str | PurePath,
            *,
            revision: Rev = None,
            encoding: str | None = None,
            return_binary: bool = False,
            ) -> str | bytes:
        full_link = self._form_abs_link(filepath, revision)
        if return_binary:
            return self.run_command('cat', full_link, return_binary=True)
        elif encoding:
            return self.run_command('cat', full_link, encoding=encoding)
        else:
            return self.run_command('cat', full_link)

    def log(
            self,
            path: str | PurePath | None = None,
            *,
            stop_on_copy: bool = False,
            limit: int | None = None,
            revision: Rev = None,
            from_revision: Rev = None,
            to_revision: Rev = None,
            from_datetime: datetime | None = None,
            to_datetime: datetime | None = None,
            changelist: bool = False,
            ) -> tuple[LogRecord, ...]:
        full_link = self._form_abs_link(path)
        args = self.__form_log_args(full_link, stop_on_copy, limit, revision, from_revision,
                                    to_revision, from_datetime, to_datetime, changelist)
        result = self.run_command('log', '--xml', *args, return_binary=True)
        return self.__parse_log_result(result.decode())

    def __form_log_args(
            self,
            full_link: str,
            stop_on_copy: bool = False,
            limit: int | None = None,
            revision: Rev = None,
            from_revision: Rev = None,
            to_revision: Rev = None,
            from_datetime: datetime | None = None,
            to_datetime: datetime | None = None,
            changelist: bool = False,
            ) -> list[str]:
        args = []
        from_revision, to_revision = self.__filter_log_revisions(from_revision, to_revision,
                                                                 from_datetime, to_datetime)
        if revision:
            full_link += f'@{revision}'
        elif not from_revision:
            full_link += f'@{to_revision}'
        else:
            args += ['-r', f'{from_revision}:{to_revision}']
        if limit is not None:
            args += ['-l', str(limit)]
        if stop_on_copy is True:
            args += ['--stop-on-copy']
        if changelist is True:
            args += ['--verbose']
        args.append(full_link)
        return args

    def __convert_datetime_to_rev(self, timestamp: datetime) -> str | None:
        return f'{{{datetime.isoformat(timestamp)}}}' if timestamp else None

    def __filter_log_revisions(
            self,
            from_revision: Rev = None,
            to_revision: Rev = None,
            from_datetime: datetime | None = None,
            to_datetime: datetime | None = None,
            ) -> (Rev, Rev):
        if from_datetime and to_datetime and from_datetime > to_datetime:
            from_datetime, to_datetime = to_datetime, from_datetime
        if from_revision and to_revision and from_revision > to_revision:
            from_revision, to_revision = to_revision, from_revision
        revision_range = [None, None]
        revision_range[0] = (
                from_revision or
                self.__convert_datetime_to_rev(from_datetime)
        )
        revision_range[1] = (
                to_revision or
                self.__convert_datetime_to_rev(to_datetime) or
                'HEAD'
        )
        return tuple(revision_range)

    def __parse_log_result(self, result: str) -> tuple[LogRecord, ...]:
        root = ElementTree.fromstring(result)
        logs = tuple(self.__parse_log(log) for log in root.findall('logentry'))
        return logs

    def __parse_log(self, log: ElementTree) -> LogRecord:
        xml = ElementTree.tostring(log, encoding=self._encoding).decode(self._encoding)
        revision = log.attrib['revision']
        author = log.find('author').text
        timestamp = log.find('date').text
        msg = log.find('msg')
        msg = msg.text if msg is not None else None
        paths = log.find('paths')
        if paths is not None:
            paths = tuple(self.__parse_log_path(path) for path in paths.findall('path'))

        return LogRecord(
                xml=xml,
                revision=revision,
                author=author,
                date=datetime.fromisoformat(timestamp),
                msg=msg,
                paths=paths,
                )

    def __parse_log_path(self, path: ElementTree) -> LogPath:
        attr = path.attrib
        prop_mods = attr['prop-mods'] == 'true'
        text_mods = attr['text-mods'] == 'true'
        kind = attr['kind']
        action = Action(attr['action'])
        return LogPath(
                prop_mods=prop_mods,
                text_mods=text_mods,
                kind=kind,
                action=action,
                path=path.text,
                )

    def export(
            self,
            from_path: str | PurePath | None,
            to_path: str | Path,
            *,
            revision: Rev = None,
            force: bool = False,
            depth: Depth = Depth.INFINITY,
            ) -> None:
        full_link = self._form_abs_link(from_path, revision)
        args = ['-q', '--depth', depth.value]
        args.append('--force') if force else None
        self.run_command('export', *args, full_link, str(to_path))

    def import_(
            self,
            from_path: str | Path,
            to_path: str | PurePath | None,
            message: str = '',
            *,
            force: bool = False,
            encoding: str | None = None,
            depth: Depth = Depth.INFINITY,
            ) -> None:
        encoding = encoding or self._encoding
        full_link = self._form_abs_link(to_path)
        args = ['-q', '--encoding', encoding, '--depth', depth.value]
        args.append('--force') if force else None
        self.run_command('import', '-m', message, *args, str(from_path), full_link)

    def mkdir(
            self,
            path: str | PurePath | None = None,
            message: str = '',
            *,
            parents: bool = False,
            encoding: str | None = None,
            exist_ok: bool = False,
            ) -> None:
        encoding = encoding or self._encoding
        full_link = self._form_abs_link(path)
        args = ['-q', '--encoding', encoding]
        args.append('--parents') if parents else None
        try:
            self.run_command('mkdir', '-m', message, *args, full_link)
        except SvnError as err:
            if not (exist_ok and 'E160020' in err.error_codes):
                raise err

    def delete(
            self,
            path: str | PurePath | None = None,
            message: str = '',
            *,
            force: bool = False,
            encoding: str | None = None,
            ) -> None:
        encoding = encoding or self._encoding
        full_link = self._form_abs_link(path)
        args = ['-q', '--encoding', encoding]
        args.append('--force') if force else None
        self.run_command('delete', '-m', message, *args, full_link)

    def list(
            self, path: str | PurePath | None = None,
            recursive: bool = False,
            revision: Rev = None,
            ) -> StorageTree:
        full_link = self._form_abs_link(path, revision)
        args = ['-R'] if recursive else []
        result = self.run_command('ls', '--xml', *args, full_link)
        return self.__parse_list(result)

    def __parse_list(self, result: str) -> StorageTree:
        root = ElementTree.fromstring(result)
        list_ = root.find('list')
        list_path = list_.attrib['path']
        nodes = tuple(self.__parse_list_node(node) for node in list_.findall('entry'))
        return StorageTree(xml=result, root=list_path, nodes=nodes)

    def __parse_list_node(self, node: ElementTree) -> StorageNode:
        xml = ElementTree.tostring(node, encoding=self._encoding).decode()
        rel_path = node.find('name').text
        kind = node.attrib['kind']
        name = Path(rel_path).name
        commit = node.find('commit')
        revision = int(commit.attrib['revision'])
        author = commit.find('author').text
        date = datetime.fromisoformat(commit.find('date').text)
        size = int(node.find('size').text) if kind == 'file' else None
        return StorageNode(
                xml=xml,
                rel_path=rel_path,
                name=name,
                revision=revision,
                author=author,
                date=date,
                size=size,
                kind=kind,
                )

    def __repr__(self) -> str:
        return f'<SVN {self.url}>'
