class QuotaExceededError(Exception):
    """Raised when a provider (LLM, TTS, or STT) reports its usage quota or rate limit is exhausted."""

    def __init__(self, provider: str, detail: str):
        self.provider = provider
        self.detail = detail
        super().__init__(f"{provider} quota exceeded: {detail}")


class ModelOverloadedError(Exception):
    """Raised when a provider reports it's temporarily overloaded (e.g. HTTP 503)."""

    def __init__(self, provider: str, detail: str):
        self.provider = provider
        self.detail = detail
        super().__init__(f"{provider} overloaded: {detail}")
