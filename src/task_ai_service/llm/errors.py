class LLMError(Exception):
    """Expected provider failure, safe to turn into an explicit fallback."""

    def __init__(self, reason: str, *, retryable: bool = False, retry_after: float = 0):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.retry_after = retry_after
