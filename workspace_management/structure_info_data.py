from datetime import datetime
from dataclasses import dataclass, field
from getpass import getuser
from socket import gethostname


@dataclass
class SvnSourceData:
    url: str
    rev: int
    repo_uuid: str
    type: str = 'svn'


@dataclass
class LocalSourceData:
    hostname: str = field(default_factory=gethostname)
    type: str = 'local'


@dataclass
class ExecData:
    filename: str
    export: SvnSourceData | LocalSourceData = None


@dataclass
class GeneralData:
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    username: str = field(default_factory=getuser)
    hostname: str = field(default_factory=gethostname)


@dataclass
class InfoRoot:
    hash_sums: dict[str, str] = field(default_factory=dict)
    exec: dict[str, ExecData] = field(default_factory=dict)
    general: GeneralData = field(default_factory=GeneralData)
