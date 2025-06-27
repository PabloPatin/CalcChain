from .base import BaseLoader, LoaderNotFoundError
from .local import LocalLoader
from .svn import SvnLoader


def handle_source(source_config: dict) -> BaseLoader:
    available_loaders = BaseLoader.__subclasses__()
    for loader_class in available_loaders:
        if loader_class.can_handle_source(source_config):
            return loader_class(source_config)
    raise LoaderNotFoundError
