import os
import shutil

from workspace_management.split_link import split_link


class LocalSourceTool:
    def load_file_from_config(self, path: str, to_local_dir: str = '',
                              local_file_name: str | None = None,
                              **kwargs) -> dict:  # noqa ARG002 ARG003
        """
        Метод загружает в рабочее пространство файл из файловой системы устройства
        :arg path: Путь к файлу на устройстве
        :param to_local_dir: Путь к директории относительно корня рабочей области,
                             куда поместить файл
        :param local_file_name: Имя файла в рабочей области (если надо переименовать)
        :param kwargs: Прочие аргументы, которые могу быть в словаре с конфигурацией
        """
        file_name = local_file_name or split_link(path)[1]
        local_path = os.path.join(to_local_dir, file_name)

        shutil.copy2(path, local_path)
        return {'file_name': file_name}

    def load_directory_from_config(self, path: str, local_path: str | None = None,
                                   **kwargs) -> None:  # noqa ARG002 ARG003
        """
        Метод загружает в рабочее пространство папку из файловой системы устройства
        :arg path: Путь к папке на устройстве
        :param local_path: Путь к папке, куда поместить содержимое относительно корня
                             рабочей области
        :param kwargs: Прочие аргументы, которые могу быть в словаре с конфигурацией
        """
        local_path = local_path or split_link(path)[1]
        shutil.copytree(path, local_path, dirs_exist_ok=True)
