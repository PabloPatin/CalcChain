import argparse
from argparse import Namespace

from workspace_management import WorkspaceManager


def main() -> None:
    args = parse_args()

    manager = WorkspaceManager(args.path_to_workdir)
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
    subparsers = parser.add_subparsers(dest="command", help="Доступные команды")

    parser_init_ws = subparsers.add_parser("init_workspace")
    parser.a
    parser.add_argument('--path', type=str)
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    main()
