import re
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePath
from typing import NoReturn


class TranslationMapError(Exception):
    pass


def create_file_translation_map(
        *,
        files: Iterable[PurePath],
        rules: Iterable[list[str, str]],  # noqa pycharm
        additional_markers: Mapping[str, str],
        check_skipped_files: bool = False,
        ) -> dict[Path, Path]:
    translation_map, skipped_files = _create_translation_map(files, rules, additional_markers)

    if check_skipped_files and skipped_files:
        skipped_files = [str(file) for file in skipped_files]
        error_message = f'some files not covered by translation rules ({skipped_files})'
        raise TranslationMapError(error_message)

    return translation_map


def _create_translation_map(
        files: Iterable[PurePath],
        rules: Iterable[list[str, str]],  # noqa pycharm
        additional_markers: Mapping[str, str],
        ) -> tuple[dict[Path, Path], list[Path]]:
    translation_map = {}
    remaining_files = list(files)

    for src_pattern, dst_pattern in rules:
        src_regex = _compile_src_pattern(src_pattern)
        matches, remaining_files = _split_files_by_pattern_matching(remaining_files, src_regex)
        for matched_file, regex_match in matches:
            dst_file = _gen_dst_file_path(
                    dst_pattern,
                    matched_file,
                    regex_match,
                    additional_markers,
                    )
            translation_map[matched_file] = dst_file

    return translation_map, remaining_files


def _compile_src_pattern(src_pattern: str) -> re.Pattern:
    try:
        return re.compile(src_pattern)
    except re.error:
        error_message = f'wrong regular expression "{src_pattern}"'
        raise TranslationMapError(error_message)


def _split_files_by_pattern_matching(
        files: Iterable[Path],
        regex: re.Pattern,
        ) -> tuple[list[tuple[Path, re.Match]], list[Path]]:
    matches = []
    remaining_files = []

    for file in files:
        match = regex.fullmatch(file.as_posix())
        if match:
            matches.append((file, match))
        else:
            remaining_files.append(file)

    return matches, remaining_files


def _gen_dst_file_path(
        dst_pattern: str,
        matched_file: Path,
        regex_match: re.Match,
        additional_markers: Mapping[str, str],
        ) -> Path:
    dst_file_path = _substitute_markers(
            dst_pattern,
            matched_file,
            regex_match,
            additional_markers,
            )
    return Path(dst_file_path)


def _substitute_markers(
        dst_pattern: str,
        matched_file: Path,
        regex_match: re.Match,
        additional_markers: Mapping[str, str],
        ) -> str:
    def raise_error(error_message: str) -> NoReturn:
        rule_desc = f'(rule "{regex_match.re.pattern}": "{dst_pattern}")'
        full_error_message = f'{error_message} {rule_desc}'
        raise TranslationMapError(full_error_message)

    def _parse_marker_key(key: str) -> tuple[str, str]:
        match = re.fullmatch(r'(\w+):(\w+)', key)
        if not match:
            error_message = f'unable to parse marker "{key}"'
            raise_error(error_message)
        return match[1], match[2]

    def repl(match: re.Match) -> str:
        key = match[1]

        if not key:
            return str(matched_file)

        if key in additional_markers:
            return additional_markers[key]

        provider, prop = _parse_marker_key(key)

        if provider == 'path':
            try:
                return str(getattr(matched_file, prop))
            except AttributeError:
                error_message = f'unknown path attribute "{prop}"'
                raise_error(error_message)

        if provider == 'capt':
            group_index = int(prop) if prop.isnumeric() else prop
            try:
                if group_index == 0:
                    raise IndexError
                return regex_match.group(group_index)
            except IndexError:
                error_message = f'wrong capture group "{group_index}"'
                raise_error(error_message)

        error_message = f'unknown marker "{key}"'
        raise_error(error_message)

    return re.sub('<(.*?)>', repl, dst_pattern)
