class NonRetryableSearchError(RuntimeError):
    """Raised when retrying the same provider call cannot fix the failure."""


class RateLimitedSearchError(RuntimeError):
    """Raised only when the provider returns an explicit rate-limit signal."""


class ProviderResponseError(NonRetryableSearchError):
    """Raised when a provider response is invalid but not explicitly rate limited."""


class TransientProviderResponseError(ProviderResponseError):
    """Raised for a narrowly identified temporary provider response."""


class ProviderParseError(NonRetryableSearchError):
    """Raised when provider rows exist but cannot be parsed into flight options."""
