import argparse
import re
from argparse import Namespace

from workspace_management import WorkspaceManager
from workspace_management.manager import AuthParam, SourceAddress


class WrongArgumentError(Exception):
    pass


def cmd_auth_callback(
        source_address: SourceAddress,
        required_params: list[AuthParam],
        ) -> dict[AuthParam, str]:
    print(f'Connecting to {source_address}...')
    auth_params = {param: input(f'{param}: ') for param in required_params}
    return auth_params


def parse_args(main_parser: argparse.ArgumentParser) -> Namespace:
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
    parent_parser.add_argument(
            '--enable_auth_cache',
            action='store_true',
            help='Включить  автоматическое кеширование',
            required=False,
            )
    parent_parser.add_argument(
            '--source-auth',
            action='append',
            nargs='+',
            required=False,
            metavar='SOURCE_ID PARAMS',
            dest='credentials',
            )

    subparsers = main_parser.add_subparsers(
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

    save_results_parser = subparsers.add_parser(
            'save-results',
            help='Сохранить результаты работы расчётного кода',
            parents=[parent_parser],
            )
    save_results_parser.add_argument(
            '--force',
            action='store_true',
            help='Пропустить проверки исходных данных и версируемости источников',
            required=False,
            )

    return main_parser.parse_args()


def check_files(ws_manager: WorkspaceManager, ignore: list[str] | None = None) -> None:
    info = ws_manager.load_ws_info()
    changed_files = ws_manager.check_hashes(info.hash_sums, ignore=ignore)
    if changed_files:
        print('Файлы изменены:')
    for file in changed_files:
        print(file)


def parse_credentials(data: list[list[str]]) -> dict[SourceAddress, dict[AuthParam, str]]:
    credentials = {}
    for auth_params in data:
        source_address = auth_params.pop(0)
        params = []
        for param in auth_params:
            match = re.fullmatch(r'(\w+)=(\w+)', param)
            if not match:
                raise WrongArgumentError(
                        f'Неверный параметр авторизации "{param}"\n'
                        'Параметры авторизации должны быть заданы в следующем виде: param=value'
                        )
            params.append((match[1], match[2]))
        credentials[source_address] = dict(params)
    return credentials


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
            prog='calc_manager',
            description='Среда для запуска расчётных скриптов',
            )
    args = parse_args(parser)

    manager = WorkspaceManager(
            args.path,
            dry_run=args.dry_run,
            auth_callback=cmd_auth_callback,
            try_save_credentials=args.enable_auth_cache,
            )

    match args.command:  # noqa pycharm
        case 'init-ws':
            if args.credentials:
                manager.set_credentials(parse_credentials(args.credentials))
            manager.initialize_ws()
        case 'check-ws':
            check_files(manager, args.ignore)
        case 'save-results':
            if args.credentials:
                manager.set_credentials(parse_credentials(args.credentials))
            manager.record_results(force=args.force)
        case _:
            print(parser.print_help())
