from .base import BaseLoader, LoaderError, LoaderNotFoundError
from .local import LocalLoader
from .svn import SvnLoader


def find_loader(source_config: dict) -> type[BaseLoader]:
    available_loaders = BaseLoader.__subclasses__()
    for loader_class in available_loaders:
        if loader_class.can_handle_source(source_config):
            return loader_class
    raise LoaderNotFoundError
