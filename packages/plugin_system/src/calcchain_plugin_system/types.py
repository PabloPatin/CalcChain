from enum import StrEnum


class CapabilityType(StrEnum):
    SOURCE = 'source'
    TARGET = 'target'
    REPORT = 'report'
    SECRETS = 'secrets'
