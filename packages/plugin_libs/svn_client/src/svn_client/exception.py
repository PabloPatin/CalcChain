import re
from typing import NamedTuple


class WarningInfo(NamedTuple):
    warning_code: str
    message: str


class ErrorInfo(NamedTuple):
    error_code: str
    message: str


class SvnError(Exception):
    """Исключение, когда утилита svn CLI вернула код ошибки"""

    def __init__(self, cmd: str, return_code: int, stdout: str, stderr: str | None, url: str):
        super().__init__()
        self.cmd = cmd
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr or '<combined with STDOUT, above>\n'
        self.url = url
        self.warnings = self.__parse_warnings()
        self.errors = self.__parse_error()

    def __parse_error(self) -> tuple[ErrorInfo, ...]:
        matches = re.findall(r'svn: ?(E\d+): ?(.*)', self.stdout + self.stderr)
        errors = tuple(ErrorInfo(err_code, msg) for err_code, msg in matches)
        return errors

    def __parse_warnings(self) -> tuple[WarningInfo, ...]:
        matches = re.findall(r'svn: ?warning: ?(W\d+): ?(.*)', self.stdout + self.stderr)
        warnings = tuple(WarningInfo(warn_code, msg) for warn_code, msg in matches)
        return warnings

    @property
    def error_codes(self) -> tuple[str]:
        return tuple(error.error_code for error in self.errors)  # noqa pycharm

    def __repr__(self) -> str:
        return f'SvnError({", ".join([err.error_code for err in self.errors])})'

    def __str__(self) -> str:
        beginning = f'Command failed with ({self.return_code}): {self.cmd}'
        stdout = f'STDOUT:\n{self.stdout}'
        stderr = f'STDERR:\n{self.stderr}'
        warnings = '\n'.join([f'{warn.warning_code}: {warn.message}' for warn in self.warnings])
        errors = '\n'.join([f'{err.error_code}: {err.message}' for err in self.errors])
        return f'{beginning}\n\n{stdout}\n{stderr}\nWARNINGS:\n{warnings}\nERRORS:\n{errors}'
