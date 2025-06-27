import shutil
import socket
from pathlib import Path

from workspace_management.config_wrapper import config
from workspace_management.loaders.base import BaseLoader
from workspace_management.mapping import create_file_translation_map


@config
class LocalLoaderConfig:
    source_type: str
    path: str


class LocalLoader(BaseLoader[LocalLoaderConfig]):
    _type = 'local'
    _config_cls = LocalLoaderConfig

    @property
    def info(self) -> dict:
        return self.config.to_dict() | {'hostname': socket.gethostname()}

    @property
    def src_files(self) -> list[Path]:
        target_dir = Path(self.config.path).resolve()
        files = [file for file in target_dir.rglob('*') if file.is_file()]
        files = [file.relative_to(target_dir.resolve()) for file in files]
        return files

    def fetch_data(self, dst_dir: str | Path, *, rules: dict[str, str]) -> None:
        files = self.src_files
        file_translation_map = create_file_translation_map(
                files=files,
                rules=rules,
                additional_markers={'root_dir': Path(self.config.path).name},
                check_skipped_files=True,
                )

        for src_file, dst_file in file_translation_map.items():
            dst_path = Path(dst_dir) / dst_file
            if not Path(dst_path).exists():
                location = Path(dst_path).parent
                location.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_path)


if __name__ == '__main__':
    loader = LocalLoader({'source_type': 'local', 'path': '123'})
    print(loader.info)
