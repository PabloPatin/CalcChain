import os
import subprocess
import time
import unittest

from svn import SvnClient
from svn.data_structures import Info, Depth, Action
from svn.exception import SvnError


class TestSvnClient(unittest.TestCase):
    WORK_PATH = os.getcwd()
    REPO_NAME = 'test_repo'
    TEST_BRANCH = 'test_branch'
    TEST_DIR = 'some_dir'
    TEST_FILE = 'some_file.txt'
    TEST_FILE_CONTENT = 'ABCxyz\nАБВэюя'

    def __create_test_repo(self):
        os.mkdir(self.repo_path)
        time.sleep(0.5)
        subprocess.run(['svnadmin', 'create', self.repo_path], env=self.env)
        time.sleep(0.5)
        subprocess.run(
                ['svn', 'mkdir', '--encoding', 'utf-8', self.branch_link, '-m',
                 'Тестовая ветка'],
                env=self.env)

    def __create_test_dir_and_file(self):
        self.test_dir_path = os.path.join(self.WORK_PATH, self.TEST_DIR)
        os.mkdir(self.test_dir_path)
        self.test_file_path = os.path.join(self.WORK_PATH, self.TEST_FILE)
        with open(self.test_file_path, 'w', encoding='utf-8') as file:
            file.write(self.TEST_FILE_CONTENT)

    def __remove_test_dir_and_file(self):
        os.rmdir(self.test_dir_path)
        os.remove(self.test_file_path)

    def setUp(self):
        self.repo_path = os.path.join(self.WORK_PATH, self.REPO_NAME).replace('\\', '/')
        self.repo_link = f'file:///{self.repo_path}'
        self.branch_link = f'{self.repo_link}/{self.TEST_BRANCH}'
        self.env = os.environ.copy()
        if not os.path.exists(self.repo_path):
            self.__create_test_repo()
        self.__create_test_dir_and_file()
        # print(self.branch_link)
        self.svn = SvnClient(self.branch_link)

    def test_info_out(self):
        info = self.svn.info()
        # pprint.pp(info)
        self.assertIsInstance(info, Info)
        self.assertEqual(info.url, self.branch_link)
        self.assertEqual(f'^/{self.TEST_BRANCH}', info.relative_url)
        self.assertEqual(f'{self.TEST_BRANCH}', info.entry_path)
        self.assertEqual('dir', info.entry_kind)

    def test_import_and_delete_file(self):
        self.svn.import_(self.test_file_path, self.TEST_FILE, message='import test file')
        info = self.svn.info(self.TEST_FILE)
        self.svn.delete(self.TEST_FILE, message='delete test file')
        try:
            info = self.svn.info(self.TEST_FILE)
        except SvnError as ex:
            self.assertEqual(ex.return_code, 1)
        # pprint.pp(info)
        self.assertEqual(f'{self.branch_link}/{self.TEST_FILE}', info.url)
        self.assertEqual(f'^/{self.TEST_BRANCH}/{self.TEST_FILE}', info.relative_url)
        self.assertEqual(self.repo_link, info.repository_root)
        self.assertEqual('file', info.entry_kind)
        self.assertEqual(f'{self.TEST_FILE}', info.entry_path)

    def test_create_and_delete_dir(self):
        self.svn.mkdir(self.TEST_DIR, message='create test dir')
        info = self.svn.info(self.TEST_DIR)
        self.svn.delete(self.TEST_DIR, message='delete test dir')
        try:
            info = self.svn.info(self.TEST_DIR)
        except SvnError as ex:
            self.assertEqual(ex.return_code, 1)
        # pprint.pp(info)
        self.assertEqual(f'{self.branch_link}/{self.TEST_DIR}', info.url)
        self.assertEqual(self.repo_link, info.repository_root)
        self.assertEqual('dir', info.entry_kind)
        self.assertEqual(f'{self.TEST_DIR}', info.entry_path)

    def test_import_and_delete_dir(self):
        self.svn.import_(self.test_dir_path, self.TEST_DIR, message='import test dir',
                         depth=Depth.EMPTY)
        info = self.svn.info(self.TEST_DIR)
        self.svn.delete(self.TEST_DIR, message='delete test dir')
        try:
            info = self.svn.info(self.TEST_DIR)
        except SvnError as ex:
            self.assertEqual(ex.return_code, 1)
        # pprint.pp(info)
        self.assertEqual(f'{self.branch_link}/{self.TEST_DIR}', info.url)
        self.assertEqual(self.repo_link, info.repository_root)
        self.assertEqual('dir', info.entry_kind)
        self.assertEqual(f'{self.TEST_DIR}', info.entry_path)

    def test_cat(self):
        self.svn.import_(self.test_file_path, self.TEST_FILE, message='import test file')
        string = self.svn.cat(self.TEST_FILE, encoding='utf-8')
        self.svn.delete(self.TEST_FILE, message='delete test file')
        self.assertIsInstance(string, str)
        self.assertEqual(string, self.TEST_FILE_CONTENT)

    def test_log(self):
        self.svn.import_(self.test_file_path, self.TEST_FILE, message='import test file')
        self.svn.delete(self.TEST_FILE, message='delete test file')
        log = self.svn.log(changelist=True)
        file_delete_log, file_add_log = log[:2]
        self.assertEqual('file', file_delete_log.paths[0].kind)
        self.assertEqual(Action.DELETE, file_delete_log.paths[0].action)
        self.assertEqual(f'/{self.TEST_BRANCH}/{self.TEST_FILE}', file_delete_log.paths[0].path)
        self.assertEqual('delete test file', file_delete_log.msg)

    def test_export_file(self):
        file_path = os.path.join(self.WORK_PATH, 'something.txt')
        self.svn.import_(self.test_file_path, self.TEST_FILE, message='import test file')
        self.svn.export(self.TEST_FILE, file_path)
        self.svn.delete(self.TEST_FILE, message='delete test file')
        condition = os.path.exists(file_path)
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        os.remove(file_path)
        self.assertTrue(condition)
        self.assertEqual(self.TEST_FILE_CONTENT, content)

    def test_list(self):
        self.svn.import_(self.test_dir_path, self.TEST_DIR, message='import test dir',
                         depth=Depth.EMPTY)
        self.svn.import_(self.test_file_path, f'{self.TEST_DIR}/{self.TEST_FILE}',
                         message='import test file')
        data = self.svn.list(recursive=True)
        self.svn.delete(self.TEST_DIR, message='delete test dir', force=True)
        # pprint.pp(data)
        self.assertEqual(self.branch_link, data.root)

    def tearDown(self):
        self.__remove_test_dir_and_file()


if __name__ == '__main__':
    unittest.main()
