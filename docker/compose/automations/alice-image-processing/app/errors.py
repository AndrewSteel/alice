"""Failure kinds of a stage (PROJ-115/117 rules)."""


class PermanentError(Exception):
    """Cannot go away by retrying (broken file, not decodable, over the pixel limit): failed_permanent at once."""


class TransientError(Exception):
    """Retry by backoff (vision model failed, unusable answer, Geoapify error)."""
