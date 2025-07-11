from .base import BaseLoader, LoaderError, LoaderNotFoundError, BaseRecorder, RecorderNotFoundError
from .local import LocalLoader
from .svn import SvnLoader


def find_loader(source_config: dict) -> type[BaseLoader]:
    available_loaders = BaseLoader.__subclasses__()
    for loader_class in available_loaders:
        if loader_class.can_handle_source(source_config):
            return loader_class
    raise LoaderNotFoundError


def find_recorder(source_config: dict) -> type[BaseRecorder]:
    available_recorders = BaseRecorder.__subclasses__()
    for recorder_class in available_recorders:
        if recorder_class.can_handle_source(source_config):
            return recorder_class
    raise RecorderNotFoundError
