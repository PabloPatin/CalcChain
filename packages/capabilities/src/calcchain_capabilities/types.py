from enum import StrEnum

class CapabilityType(StrEnum):
    AUTH = 'auth'
    SOURCE = 'source'
    TARGET = 'target'
    REPORT = 'report'