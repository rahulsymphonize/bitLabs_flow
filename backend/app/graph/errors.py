class GraphError(Exception):
    """Base for errors the API maps to a status code."""


class LLMUnavailable(GraphError):
    """Provider down, rate limited or timed out."""


class LLMTimeout(LLMUnavailable):
    pass


class LLMBadOutput(GraphError):
    """Provider answered but not with usable structured output."""


class SourceUnreadable(GraphError):
    """Uploaded file cannot be parsed into text."""
