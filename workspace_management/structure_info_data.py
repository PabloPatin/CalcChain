from dataclasses import dataclass, field
from datetime import datetime, UTC
from getpass import getuser
from socket import gethostname


@dataclass
class GeneralData:
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).astimezone().isoformat())
    username: str = field(default_factory=getuser)
    hostname: str = field(default_factory=gethostname)


@dataclass
class Info:
    hash_sums: dict[str, str] = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)
    general: GeneralData = field(default_factory=GeneralData)
