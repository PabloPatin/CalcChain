import os
from typing import Literal

from svn import SvnClient, data_structures
from workspace_management.split_link import split_link


class SvnTool:
    def __init__(self) -> None:
        self.svn_client = None

    def load_file_from_config(self, url: str, to_local_dir: str = '',
                              revision: int | None = None, local_file_name: str | None = None,
                              **kwargs) -> data_structures.Info:  # noqa ARG002 ARG003
        """
        Метод загружает в рабочее пространство файл из репозитория
        :arg url: Ссылка на файл в репозитории
        :param to_local_dir: Путь к директории относительно корня рабочей области,
                             куда поместить файл
        :param revision: Ревизия репозитория (по умолчанию HEAD)
        :param local_file_name: Имя файла в рабочей области (если надо переименовать)
        :param kwargs: Прочие аргументы, которые могу быть в словаре с конфигурацией
        :return: Возвращает номер ревизии файла
        """
        repo_link, rel_path = split_link(url)
        if not local_file_name:
            local_file_name = rel_path
        local_path = os.path.join(to_local_dir, local_file_name)
        self.svn_client = SvnClient(repo_link)
        self.svn_client.export(rel_path, local_path, revision=revision)
        return self.svn_client.info(rel_path)

    def load_directory_from_config(self, url: str, local_path: str | None = None,
                                   revision: Literal['HEAD'] | int | None = None,
                                   **kwargs) -> data_structures.Info:  # noqa ARG002 ARG003
        """
        Метод загружает в рабочее пространство папку из репозитория
        :arg url: Ссылка на папку в репозитории
        :param local_path: Путь к директории относительно корня рабочей области, куда поместить
                             содержимое папки (создаст автоматически если не существует)
        :param revision: Ревизия репозитория (по умолчанию HEAD)
        :param kwargs: Прочие аргументы, которые могу быть в словаре с конфигурацией
        :return: Возвращает номер ревизии папки
        """
        local_path = local_path or split_link(url)[1]
        self.svn_client = SvnClient(url)
        self.svn_client.export(from_rel_path=None, to_path=local_path, revision=revision,
                               force=True)
        return self.svn_client.info()
