from collections.abc import Iterable, Mapping
from pathlib import Path, PurePath
import re
from typing import NoReturn


class TranslationMapError(Exception):
    pass


def create_file_translation_map(
    *,
    files: Iterable[PurePath],
    rules: Iterable[list[str]],
    additional_markers: Mapping[str, str],
    check_skipped_files: bool = False,
) -> dict[Path, Path]:
    translation_map, skipped_files = _create_translation_map(files, rules, additional_markers)

    if check_skipped_files and skipped_files:
        skipped = [str(file) for file in skipped_files]
        raise TranslationMapError(f'some files not covered by translation rules ({skipped})')

    return translation_map


def _create_translation_map(
    files: Iterable[PurePath],
    rules: Iterable[list[str]],
    additional_markers: Mapping[str, str],
) -> tuple[dict[Path, Path], list[Path]]:
    translation_map = {}
    remaining_files = list(files)

    for src_pattern, dst_pattern in rules:
        src_regex = _compile_src_pattern(src_pattern)
        matches, remaining_files = _split_files_by_pattern_matching(remaining_files, src_regex)
        for matched_file, regex_match in matches:
            dst_file = _gen_dst_file_path(dst_pattern, matched_file, regex_match, additional_markers)
            translation_map[matched_file] = dst_file

    return translation_map, remaining_files


def _compile_src_pattern(src_pattern: str) -> re.Pattern:
    try:
        return re.compile(src_pattern)
    except re.error as err:
        raise TranslationMapError(f'wrong regular expression "{src_pattern}"') from err


def _split_files_by_pattern_matching(
    files: Iterable[Path],
    regex: re.Pattern,
) -> tuple[list[tuple[Path, re.Match]], list[Path]]:
    matches = []
    remaining_files = []

    for file in files:
        match = regex.fullmatch(_match_path(file))
        if match:
            matches.append((file, match))
        else:
            remaining_files.append(file)

    return matches, remaining_files


def _match_path(file: PurePath) -> str:
    return file.as_posix().replace('\\', '/')


def _gen_dst_file_path(
    dst_pattern: str,
    matched_file: Path,
    regex_match: re.Match,
    additional_markers: Mapping[str, str],
) -> Path:
    return Path(_substitute_markers(dst_pattern, matched_file, regex_match, additional_markers))


def _substitute_markers(
    dst_pattern: str,
    matched_file: Path,
    regex_match: re.Match,
    additional_markers: Mapping[str, str],
) -> str:
    def raise_error(error_message: str) -> NoReturn:
        rule_desc = f'(rule "{regex_match.re.pattern}": "{dst_pattern}")'
        raise TranslationMapError(f'{error_message} {rule_desc}')

    def parse_marker_key(key: str) -> tuple[str, str]:
        match = re.fullmatch(r'(\w+):(\w+)', key)
        if not match:
            raise_error(f'unable to parse marker "{key}"')
        return match[1], match[2]

    def replace_marker(match: re.Match) -> str:
        key = match[1]

        if not key:
            return str(matched_file)

        if key in additional_markers:
            return additional_markers[key]

        provider, prop = parse_marker_key(key)

        if provider == 'path':
            try:
                return str(getattr(matched_file, prop))
            except AttributeError:
                raise_error(f'unknown path attribute "{prop}"')

        if provider == 'capt':
            group_index = int(prop) if prop.isnumeric() else prop
            try:
                if group_index == 0:
                    raise IndexError
                return regex_match.group(group_index)
            except IndexError:
                raise_error(f'wrong capture group "{group_index}"')

        raise_error(f'unknown marker "{key}"')

    return re.sub('<(.*?)>', replace_marker, dst_pattern)
