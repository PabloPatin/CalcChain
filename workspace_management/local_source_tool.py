import os
import shutil

from workspace_management.abstract import AbstractManager


class LocalSourceTool(AbstractManager):
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
        file_name = local_file_name or self.split_link(path)[1]
        local_path = os.path.join(to_local_dir, file_name)

        shutil.copy2(path, local_path)
        return {'file_name': file_name}
