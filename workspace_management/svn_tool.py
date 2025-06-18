import os.path

from workspace_management.abstract import AbstractManager

from svn import SvnClient


class SvnTool(AbstractManager):
    def __init__(self, path_to_workspace: str):
        super().__init__(path_to_workspace)
        self.svn_client = None

    def split_link(self, link: str) -> tuple[str, str]:
        last_sep = max(link.rfind('/'), link.rfind('\\'))
        return link[:last_sep], link[last_sep + 1:]

    def load_file_from_config(self, from_link: str, to_local_path: str = '',
                              revision: int | None = None, local_file_name: str | None = None,
                              **kwargs) -> None: # noqa ARG002 ARG003
        repo_link, rel_path = self.split_link(from_link)
        if not local_file_name:
            local_file_name = rel_path
        local_path = os.path.join(self.work_path, to_local_path, local_file_name)
        self.svn_client = SvnClient(repo_link)
        self.svn_client.export(rel_path, local_path, revision=revision)
