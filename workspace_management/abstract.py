from abc import ABCMeta


class AbstractManager(metaclass=ABCMeta):
    __exec_rel_path = 'exec'

    def __init__(self, path_to_workspace: str):
        self.work_path = path_to_workspace
