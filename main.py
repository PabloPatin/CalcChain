import argparse

from workspace_manager import WorkspaceManager

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path_to_workdir')
    args = parser.parse_args()
    print(args)
    manager = WorkspaceManager(args.path_to_workdir)
    manager.read_toml()

if __name__ == '__main__':
    main()



