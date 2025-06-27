from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from collections.abc import Iterable, Mapping
from itertools import filterfalse, tee
from pathlib import Path
from typing import Any


class SkippedFilesError(Exception):
    pass


class UnknownMarkerError(Exception):
    pass


def create_file_translation_map(
        *,
        files: Iterable[Path],
        rules: Mapping[str, str],
        additional_markers: Mapping[str, str],
        check_skipped_files: bool = False,
        ) -> dict[Path, Path]:
    translation_map, skipped_files = _create_translation_map(files, rules, additional_markers)

    if check_skipped_files and skipped_files:
        skipped_files = [str(file) for file in skipped_files]
        error_message = f'some files not covered by translation rules ({skipped_files})'
        raise SkippedFilesError(error_message)

    return translation_map


def _create_translation_map(
        files: Iterable[Path],
        rules: Mapping[str, str],
        additional_markers: Mapping[str, str],
        ) -> tuple[dict[Path, Path], list[Path]]:
    translation_map = {}
    remaining_files = list(files)

    for src_pattern, dst_pattern in rules.items():
        matches, remaining_files = _split_files_by_pattern_matching(remaining_files, src_pattern)
        for matched_file in matches:
            dst_file = _gen_dst_file_path(dst_pattern, matched_file, additional_markers)
            translation_map[matched_file] = dst_file

    return translation_map, remaining_files


def _split_files_by_pattern_matching(
        files: Iterable[Path],
        pattern: str,
        ) -> tuple[list[Path], list[Path]]:
    def split_iterable(
            it: Iterable[Any],
            predicate: Callable[[Any], bool],
            ) -> tuple[list[Any], list[Any]]:
        it1, it2 = tee(it)
        return list(filter(predicate, it1)), list(filterfalse(predicate, it2))

    def is_match(file: Path) -> bool:
        return fnmatch.fnmatchcase(file.as_posix(), pattern)

    return split_iterable(files, is_match)


def _gen_dst_file_path(
        dst_pattern: str,
        matched_file: Path,
        additional_markers: Mapping[str, str],
        ) -> Path:
    tokens = _tokenize_dst_pattern(dst_pattern)
    tokens = [_substitute_markers(token, matched_file, additional_markers)
              for token in tokens]
    return Path().joinpath(*tokens)


def _tokenize_dst_pattern(dst_pattern: str) -> list[str]:
    tokens = re.split('(<.*?>)', dst_pattern)
    tokens = [token.strip(r'\/') for token in tokens]
    tokens = [token for token in tokens if token]
    return tokens


def _substitute_markers(
        token: str,
        matched_file: Path,
        additional_markers: Mapping[str, str],
        ) -> str:
    def repl(match: re.Match) -> str:
        key = match[1]

        if key == 'path':
            return str(matched_file)

        if key == 'name':
            return matched_file.name

        if key == 'parent':
            return str(matched_file.parent)

        if key in additional_markers:
            return additional_markers[key]

        raise UnknownMarkerError(key)

    return re.sub('^<(.*)>$', repl, token)
