import os.path

from workspace_management.abstract import AbstractManager

from svn import SvnClient, data_structures


class SvnTool(AbstractManager):
    def __init__(self, path_to_workspace: str):
        super().__init__(path_to_workspace)
        self.svn_client = None

    def load_file_from_config(self, link: str, to_local_dir: str = '',
                              revision: int | None = None, local_file_name: str | None = None,
                              **kwargs) -> data_structures.Info: # noqa ARG002 ARG003
        """
        Метод загружает в рабочее пространство файл из репозитория
        :arg link: Ссылка на файл в репозитории
        :param to_local_dir: Путь к директории относительно корня рабочей области,
                             куда поместить файл
        :param revision: Ревизия репозитория (по умолчанию HEAD)
        :param local_file_name: Имя файла в рабочей области (если надо переименовать)
        :param kwargs: Прочие аргументы, которые могу быть в словаре с конфигурацией
        :return: Возвращает номер ревизии файла
        """
        repo_link, rel_path = self.split_link(link)
        if not local_file_name:
            local_file_name = rel_path
        local_path = os.path.join(self.work_path, to_local_dir, local_file_name)
        self.svn_client = SvnClient(repo_link)
        self.svn_client.export(rel_path, local_path, revision=revision)
        return self.svn_client.info(rel_path)

