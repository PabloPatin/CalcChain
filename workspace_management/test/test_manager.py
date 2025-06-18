import os
import unittest
from workspace_management import WorkspaceManager
from workspace_management.manager import PathNotFoundError, IncorrectDirectoryError


class TestWorkspaceManager(unittest.TestCase):
    def test_unknown_path_init(self):
        try:
            manager = WorkspaceManager('some_dir')
        except Exception as ex:
            self.assertIsInstance(ex, PathNotFoundError)

    def test_wrong_content_init(self):
        os.mkdir('some_dir')
        with open('some_dir/some_file.txt', 'wb') as file:
            file.write(b'abc')
        try:
            manager = WorkspaceManager('some_dir')
        except Exception as ex:
            self.assertIsInstance(ex, IncorrectDirectoryError)
        os.remove('some_dir/some_file.txt')
        os.rmdir('some_dir')

    def test_right_init(self):
        os.mkdir('some_dir')
        with open('some_dir/config.toml', 'w', encoding='utf-8') as file:
            file.write('[exec]\npath = "."')
        try:
            manager = WorkspaceManager('some_dir')
        except Exception as ex:
            pass
        else:
            self.assertIsInstance(manager, WorkspaceManager)
        os.remove('some_dir/config.toml')
        os.rmdir('some_dir')

if __name__ == '__main__':
    unittest.main()
