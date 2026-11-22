"""Error kinds of an extraction. Messages are shown in the register: plain German, no NAS paths."""


class ExtractionError(Exception):
    pass


class PermanentError(ExtractionError):
    """Cannot go away by retrying (password, broken file, unsupported variant, too large) → failed_permanent."""


class TransientError(ExtractionError):
    """Timeout, crash of the converter, out of memory → normal backoff of the register."""
