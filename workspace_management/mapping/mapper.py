from collections.abc import Mapping
from pathlib import Path
from collections.abc import Callable


class RuleError(Exception):
    pass


class MarkerNotFoundError(RuleError):
    def __init__(self, marker: str, msg: str):
        super().__init__(f'Маркер не найден {marker}\n' + msg)


class FileMapper:
    _markers: dict[str, Callable[[Path], str]] = {
        '<path>': lambda _: str(_),
        '<name>': lambda _: _.name,
        '<parent>': lambda _: str(_.parent),
        }

    def __init__(self, rules: Mapping[str, str], **global_markers: dict[str, str]):
        self.rules = [(src, dst) for src, dst in rules]
        self._global_markers = {f'<{marker}>': value for marker, value in global_markers.items()}

    @property
    def markers(self):
        return self._markers.keys() | self.global_markers.keys()

    @property
    def global_markers(self):
        return self._global_markers


if __name__ == '__main__':
    test_files = [
        Path('loaders/001.txt'),
        Path('loaders/002.txt'),
        Path('loaders/base.py'),
        Path('loaders/local.py'),
        Path('loaders/svn.py'),
        Path('loaders/__init__.py'),
        Path('main.py'),
        Path('test{123}.txt'),
        ]

    file_translation_rules = {
        'loaders/__*': 'DATA/<path>',
        'loaders/base.*': 'DATA\\<root_dir>/<path>',
        'loaders/*.py': '<path>',
        'loaders/*': '<parent>/aaa/<name>',
        '*': 'DATA/<name>',
        }

    FileMapper(rules=file_translation_rules)
