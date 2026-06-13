class NonRetryableSearchError(RuntimeError):
    """Raised when retrying the same provider call cannot fix the failure."""
