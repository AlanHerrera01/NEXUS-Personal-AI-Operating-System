class LLMProviderError(Exception):
    pass


class LLMAuthenticationError(LLMProviderError):
    pass


class LLMRateLimitError(LLMProviderError):
    pass


class LLMTimeoutError(LLMProviderError):
    pass


class LLMUnavailableError(LLMProviderError):
    pass


class LLMInvalidRequestError(LLMProviderError):
    pass
