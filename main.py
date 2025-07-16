import argparse
from argparse import Namespace
from collections.abc import Iterable

from workspace_management import WorkspaceManager


def cmd_auth_callback(
        type: str,
        source_address: str,
        required_params: Iterable[str],
        ) -> dict[str, str]:
    print(f'Connecting to {type}...\n{source_address}')
    auth_params = {param: input(f'{param}: ') for param in required_params}
    return auth_params


def parse_args(parser: argparse.ArgumentParser) -> Namespace:
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
            '-p', '--path',
            type=str,
            metavar='WS_PATH',
            help='Путь к рабочей области',
            required=True,
            )

    parent_parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Запустить без внесения изменений',
            required=False,
            )

    subparsers = parser.add_subparsers(
            dest='command',
            title='Команды программы',
            required=True,
            metavar='{init-ws, check-ws}',
            )

    subparsers.add_parser(
            'init-ws', aliases=['initialise-workspace'],
            help='Создать рабочую область',
            description='Принимает путь к пустой директории с файлом config.toml. '
                        'Загружает исполняемые данные и исходные файлы '
                        'в соответствии с конфигурацией.',
            parents=[parent_parser],
            )

    hash_check_parser = subparsers.add_parser(
            'check-ws', aliases=['check-workspace-file-hashes'],
            help='Проверить наличие изменённых файлов',
            description='Сверяет хэши всех файлов в рабочей области '
                        'и находит файлы, которые были изменены.',
            parents=[parent_parser],
            )

    hash_check_parser.add_argument(
            '--ignore',
            nargs='*',
            help='Пути в рабочей области, которые не надо проверять',
            type=str,
            metavar='PATH',
            required=False,
            )

    subparsers.add_parser(
            'save-results',
            help='Сохранить результаты работы расчётного кода',
            parents=[parent_parser],
            )

    args = parser.parse_args()
    return args


def check_files(manager: WorkspaceManager, ignore: list[str] | None = None) -> None:
    info = manager.load_ws_info()
    changed_files = manager.check_hashes(info.hash_sums, ignore=ignore)
    if changed_files:
        print('Файлы изменены:')
    for file in changed_files:
        print(file)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
            prog='calc_manager',
            description='Среда для запуска расчётных скриптов',
            )
    args = parse_args(parser)

    manager = WorkspaceManager(args.path, dry_run=args.dry_run, auth_callback=cmd_auth_callback)

    match args.command:
        case 'init-ws':
            manager.initialize_ws()
        case 'check-ws':
            check_files(manager, args.ignore)
        case 'save-results':
            manager.record_results()
        case _:
            print(parser.print_help())
