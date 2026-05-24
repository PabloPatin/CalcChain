from pathlib import Path


class LogWriter:
    def __init__(self, path: Path):
        self.path = Path(path)

    def write_text(self, text: str) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('w', encoding='utf-8', newline='\n') as file:
            file.write(text)
        return self.path


def decode_process_stream(data: bytes, encoding: str) -> str:
    return data.decode(encoding, errors='replace')


def write_stdin_text(logs_dir: Path, text: str) -> Path:
    return LogWriter(Path(logs_dir) / 'stdin.txt').write_text(text)


def write_process_stream(
    logs_dir: Path,
    name: str,
    data: bytes,
    encoding: str,
    *,
    secret_values: list[str] | None = None,
) -> Path:
    text = decode_process_stream(data, encoding)
    for secret_value in secret_values or []:
        if secret_value:
            text = text.replace(secret_value, '[secret]')
    return LogWriter(Path(logs_dir) / name).write_text(text)
