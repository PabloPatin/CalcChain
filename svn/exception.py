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

    def __init__(self, cmd: str, return_code: int, stdout: str, stderr: str | None):
        super().__init__()
        self.cmd = cmd
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr or '<combined with STDOUT, above>\n'
        self.warnings = self.__parse_warnings()
        self.errors = self.__parse_error()

    def __parse_error(self) -> ErrorInfo | None:
        match = re.search(r'svn: ?(E\d+): ?(.*)', self.stdout + self.stderr)
        errors = []
        if match:
            groups = match.groups()
            for code in groups[::2]:
                for message in groups[1::2]:
                    errors.append(ErrorInfo(code, message))
            return tuple(errors)  # noqa pycharm
        else:
            return None

    def __parse_warnings(self) -> tuple[WarningInfo] | None:
        match = re.search(r'svn: ?warning: ?(W\d+): ?(.*)', self.stdout + self.stderr)
        warnings = []
        if match:
            groups = match.groups()
            for code in groups[::2]:
                for message in groups[1::2]:
                    warnings.append(WarningInfo(code, message))
            return tuple(warnings)  # noqa pycharm
        else:
            return None

    @property
    def error_codes(self):
        return [error.error_code for error in self.errors]

    def __str__(self) -> str:
        beginning = f'Command failed with ({self.return_code}): {self.cmd}'
        stdout = f'STDOUT:\n{self.stdout}'
        stderr = f'STDERR:\n{self.stderr}'
        warnings = '\n'.join([f'{warn.warning_code}: {warn.message}' for warn in self.warnings]) \
            if self.warnings else ''
        error = f'{self.errors.error_code}: {self.errors.message}'
        return f'{beginning}\n\n{stdout}\n{stderr}\nWARNINGS:\n{warnings}\nERRORS:\n{error}'
