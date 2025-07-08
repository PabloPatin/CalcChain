import logging
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .config import LANG
from .exception import SvnError

_LOGGER = logging.getLogger(__name__)


class Commander:
    def external_command(
            self, cmd: str | Sequence[str], split_lines: bool = False, return_binary: bool = False,
            environment: dict | None = None, wd: str | Path | None = None,
            join_stderr: bool = False, encoding: str | None = None) -> str | list[str] | bytes:
        """Выполнение команд в консоли и обработка ошибок

        :arg cmd: Команда со всеми её аргументами
        :param split_lines: Делит выходной текст по строкам
        :param return_binary:
        :param environment:
        :param wd:
        :param join_stderr:
        :param encoding:"""
        _LOGGER.debug(f'RUN: {cmd}')
        env = self.set_env(environment)
        wd = Path(wd) if wd else Path()
        if not wd.is_dir():
            raise FileNotFoundError('Рабочая директория не найдена')

        if return_binary:
            encoding = None

        p = subprocess.Popen(
                cmd,
                cwd=wd.resolve(),
                env=env,
                stdout=subprocess.PIPE,
                universal_newlines=not return_binary,
                stderr=subprocess.STDOUT if join_stderr else subprocess.PIPE,
                encoding=encoding,
                )
        stdout, stderr = p.communicate()
        return_code = p.returncode

        self.check_error(cmd, return_code, stdout, stderr)

        if return_binary or not split_lines:
            return stdout

        return stdout.strip('\n').split('\n')

    def check_error(self, cmd: str | Sequence[str], return_code: int, stdout: str,
                    stderr: str) -> None:
        """Проверка наличия ошибок в результате работы функции"""
        if return_code != 0:
            if stderr is None:
                stderr = '<combined with STDOUT, above>'
            raise SvnError(cmd, return_code, stdout, stderr)

    def set_env(self, environment: dict[str, str]) -> dict[str, str]:
        """Подготовка переменных среды"""
        env = os.environ.copy()
        env['LANG'] = LANG
        if environment:
            env.update(environment)
        return env
