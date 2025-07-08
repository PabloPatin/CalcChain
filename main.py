import argparse
from argparse import Namespace

from workspace_management import WorkspaceManager


def main() -> None:
    args = parse_args()
    match args.command:
        case 'init-ws':
            manager = WorkspaceManager(args.path)
            init_workspace(manager)


def init_workspace(manager: WorkspaceManager) -> None:
    manager.read_config()
    manager.load_exec()
    manager.load_data()
    manager.dump_config()
    manager.hash_ws_files()
    manager.dump_info()


def parse_args() -> Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', help='Доступные команды')
    initial_parser = subparsers.add_parser('init-ws', help='Инициализатор рабочей области')
    initial_parser.add_argument('--path', type=str)
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    main()
