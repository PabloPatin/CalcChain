from abc import ABCMeta


class AbstractManager(metaclass=ABCMeta):
    __exec_rel_path = 'exec'

    def __init__(self, path_to_workspace: str):
        self.work_path = path_to_workspace

    def split_link(self, link: str) -> tuple[str, str]:
        """
        Делит ссылку на путь до объекта ие его название
        :param link: Ссылка или путь
        :return: Кортеж вида ([путь до объекта], [имя объекта])
        """
        last_sep = max(link.rfind('/'), link.rfind('\\'))
        return link[:last_sep], link[last_sep + 1:]