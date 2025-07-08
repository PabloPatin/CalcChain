from dataclasses import dataclass, field, is_dataclass
from datetime import datetime, UTC
from getpass import getuser
from socket import gethostname


@dataclass
class GeneralData:
    username: str = field(default_factory=getuser)
    hostname: str = field(default_factory=gethostname)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).astimezone().isoformat())


@dataclass
class Info:
    general: GeneralData = field(default_factory=GeneralData)
    sources: list[dict] = field(default_factory=list)
    hash_sums: dict[str, str] = field(default_factory=dict)


def dataclass_from_dict[T](data: dict, cls: type[T]) -> T:
    for field_name, field_data in cls.__dataclass_fields__.items():
        if is_dataclass(field_data.type):
            data[field_name] = dataclass_from_dict(data.get(field_name), field_data.type)
    return cls(**data)
