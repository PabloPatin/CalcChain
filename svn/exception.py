class SvnError(Exception):
    """Исключение, когда утилита svn CLI вернула код ошибки"""
    def __init__(self, cmd: str, return_code: int, stdout: str, stderr: str | None):
        super().__init__()
        self.cmd = cmd
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr or '<combined with STDOUT, above>'

    def __str__(self) -> str:
        return (f'Command failed with ({self.return_code}): {self.cmd}\n'
                f'STDOUT:\n{self.stdout}\nSTDERR:\n{self.stderr}')
