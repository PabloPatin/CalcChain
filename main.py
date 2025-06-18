import argparse

from workspace_management import WorkspaceManager

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('path_to_workdir')
    args = parser.parse_args()
    manager = WorkspaceManager(args.path_to_workdir)
    manager.read_toml()
    manager.load_exec('sapfir')

if __name__ == '__main__':
    main()



