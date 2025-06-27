import importlib
from pathlib import Path

from .base import BaseLoader, LoaderNotFoundError


def handle_source(source_config: dict) -> BaseLoader:
    available_loaders = BaseLoader.__subclasses__()
    for loader_class in available_loaders:
        if loader_class.can_handle_source(source_config):
            return loader_class(source_config)
    raise LoaderNotFoundError


# TODO: такое решение убивает типизацию конфигурации, так как она не встроена в BaseLoader
def _get_loader_modules() -> list[str]:
    search_dir = Path(__file__).resolve().parent
    found_files = search_dir.glob('*.py')
    excludes = ['__init__.py', 'base.py']
    return [f'{__name__}.{file.stem}' for file in found_files if
            not file.name in excludes]


for loader_module in _get_loader_modules():
    importlib.import_module(loader_module)
