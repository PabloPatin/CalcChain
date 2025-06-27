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
    manager.dump_info()
    manager.dump_config()


def parse_args() -> Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('path_to_workdir')
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    main()
