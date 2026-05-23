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


class BuildExecutionError(CalcChainError):
    """Raised when a checked build plan cannot be materialized safely."""


class RunExecutionError(CalcChainError):
    """Raised when a run process cannot be started or recorded safely."""


class PublishError(CalcChainError):
    """Raised when publication cannot be planned or executed safely."""


class RestoreError(CalcChainError):
    """Raised when restore cannot reconstruct or verify a job safely."""


class CleanupError(CalcChainError):
    """Raised when cleanup cannot safely remove work files."""


class ReportError(CalcChainError):
    """Raised when a report capability cannot render or export safely."""
