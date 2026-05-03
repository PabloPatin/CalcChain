class CalcChainError(Exception):
    """Base CalcChain core error."""


class ConfigFormatError(CalcChainError):
    """Raised when a CalcChain format file has an invalid shape."""


class UnsupportedSchemaVersionError(ConfigFormatError):
    """Raised when a format file uses an unsupported schema version."""


class SourceError(CalcChainError):
    """Raised when a source cannot be read or resolved."""


class RulesError(CalcChainError):
    """Raised when rules cannot be loaded or applied safely."""


class BuildPlanError(CalcChainError):
    """Raised when a build lock cannot produce a safe build plan."""
