from dataclasses import dataclass, field
from datetime import datetime, timezone
from getpass import getuser
from socket import gethostname
from typing import Literal


@dataclass
class Source:
    type: Literal['exec', 'data', 'res_data']


@dataclass
class SvnSource(Source):
    url: str
    rev: int
    repo_uuid: str
    export_type: str = 'svn'


@dataclass
class LocalSource(Source):
    hostname: str = field(default_factory=gethostname)
    export_type: str = 'local'


@dataclass
class GeneralData:
    timestamp: str = field(
            default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat())
    username: str = field(default_factory=getuser)
    hostname: str = field(default_factory=gethostname)


HashSum = str
FilePath = str


@dataclass
class InfoRoot:
    hash_sums: dict[FilePath, HashSum] = field(default_factory=dict)
    sources: list[Source] = field(default_factory=list)
    general: GeneralData = field(default_factory=GeneralData)
