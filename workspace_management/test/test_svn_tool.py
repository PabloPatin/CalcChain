import os
import shutil
import subprocess
import time
import unittest

from svn import SvnClient
from svn.exception import SvnError
from workspace_management.svn_tool import SvnTool


class TestSvnTool(unittest.TestCase):
    WORK_PATH = os.getcwd()
    REPO_NAME = 'test_repo'
    TEST_BRANCH = 'test_branch'
    TEST_EXEC_DIR = 'exec'
    TEST_SAPFIR_FILE = 'sapfir.exe.txt'
    TEST_SAPFIR_FILE_CONTENT = 'Сапфирозаменитель'
    TEST_WORKSPACE = 'test_workspace'
    os.chdir(TEST_WORKSPACE)
    svn_tool = SvnTool()

    def __create_test_repo(self):
        os.mkdir(self.repo_path)
        time.sleep(0.5)
        subprocess.run(['svnadmin', 'create', self.repo_path], env=self.env)
        time.sleep(0.5)
        subprocess.run(['svn', 'mkdir', '--encoding', 'utf-8', self.branch_link, '-m',
                        'Тестовая ветка'], env=self.env)

    def __fill_test_repo(self):
        svn = SvnClient(self.branch_link)
        self.__fill_if_not_exist(svn, self.TEST_EXEC_DIR, isdir=True)
        self.__fill_if_not_exist(svn, self.TEST_EXEC_DIR, filename=self.TEST_SAPFIR_FILE,
                                 content=self.TEST_SAPFIR_FILE_CONTENT)

    def __exists(self, client: SvnClient, rel_path):
        try:
            client.info(rel_path)
        except SvnError:
            return False
        return True

    def __fill_if_not_exist(self, client: SvnClient, rel_path='',
                            isdir=False, filename='', content=''):
        if isdir:
            if not self.__exists(client, rel_path):
                client.mkdir(rel_path, parents=True)
        else:
            rel_path = f'{rel_path}/{filename}'
            if not self.__exists(client, rel_path):
                file_path = os.path.join(self.WORK_PATH, filename)
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(content)
                client.import_(file_path, rel_path)
                os.remove(file_path)

    def setUp(self):
        self.repo_path = os.path.join(self.WORK_PATH, self.REPO_NAME).replace('\\', '/')
        self.repo_link = f'file:///{self.repo_path}'
        self.branch_link = f'{self.repo_link}/{self.TEST_BRANCH}'
        self.env = os.environ.copy()
        if not os.path.exists(self.repo_path):
            self.__create_test_repo()
        self.__fill_test_repo()
        test_workspace_path = os.path.join(self.WORK_PATH, self.TEST_WORKSPACE)
        if not os.path.exists(test_workspace_path):
            os.mkdir(test_workspace_path)

    def test_file_loading_without_renaming(self):
        test_file_link = f'{self.branch_link}/{self.TEST_EXEC_DIR}/{self.TEST_SAPFIR_FILE}'
        self.svn_tool.load_file_from_config(test_file_link)
        local_file_path = os.path.join(self.TEST_WORKSPACE, self.TEST_SAPFIR_FILE)
        self.assertTrue(os.path.exists(local_file_path))
        os.remove(local_file_path)

    def test_file_loading_with_renaming(self):
        test_file_link = f'{self.branch_link}/{self.TEST_EXEC_DIR}/{self.TEST_SAPFIR_FILE}'
        self.svn_tool.load_file_from_config(test_file_link, local_file_name='new_sapfir.example')
        local_file_path = os.path.join(self.TEST_WORKSPACE, 'new_sapfir.example')
        self.assertTrue(os.path.exists(local_file_path))
        os.remove(local_file_path)

    def tearDown(self):
        shutil.rmtree('test_workspace')


if __name__ == '__main__':
    unittest.main()
