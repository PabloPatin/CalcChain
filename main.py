import argparse
from argparse import Namespace

from workspace_management import WorkspaceManager


def main() -> None:
    args = parse_args()
    match args.command:
        case 'init-ws':
            manager = WorkspaceManager(args.path, check_init=True)
            init_workspace(manager)
        case 'check-ws':
            manager = WorkspaceManager(args.path)
            check_files(manager)
        case _:
            print(parser.print_help())


def init_workspace(manager: WorkspaceManager) -> None:
    manager.read_config()
    manager.load_exec()
    manager.load_data()
    manager.lock_config()
    manager.hash_ws_files()
    manager.save_ws_info()


def check_files(manager: WorkspaceManager) -> None:
    info = manager.load_ws_info()
    changed_files = manager.check_hashes(info.hash_sums)
    if changed_files:
        print('Файлы изменены:')
    for file in changed_files:
        print(file)


def parse_args() -> Namespace:
    subparsers = parser.add_subparsers(dest='command', help='Доступные команды')

    initial_parser = subparsers.add_parser('init-ws', help='Инициализатор рабочей области')
    initial_parser.add_argument('-p', '--path', type=str)

    hash_check_parser = subparsers.add_parser('check-ws', help='Проверка изменения файлов')
    hash_check_parser.add_argument('-p', '--path', type=str)
    hash_check_parser.add_argument('--skip-files', nargs='+', type=str)

    args = parser.parse_args()
    return args


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    main()
