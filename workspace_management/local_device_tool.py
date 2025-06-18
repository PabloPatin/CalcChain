import os

from workspace_management.abstract import AbstractManager
import shutil


class LocalDeviceTool(AbstractManager):
    def load_file_from_config(self, path: str, to_local_dir: str = '',
                              local_file_name: str | None = None,
                              **kwargs) -> int:  # noqa ARG002 ARG003
        """
        Метод загружает в рабочее пространство файл из файловой системы устройства
        :arg path: Путь к файлу на устройстве
        :param to_local_dir: Путь к директории относительно корня рабочей области,
                             куда поместить файл
        :param local_file_name: Имя файла в рабочей области (если надо переименовать)
        :param kwargs: Прочие аргументы, которые могу быть в словаре с конфигурацией
        """
        local_path = os.path.join(self.work_path, to_local_dir)
        if local_file_name:
            local_path = os.path.join(local_path, local_file_name)
        print(path, local_path)
        shutil.copy2(path, local_path)
