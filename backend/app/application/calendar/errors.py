class CalendarError(Exception):
    """Base class for calendar use-case failures."""


class InvalidEventError(CalendarError):
    """The requested event violates a calendar invariant.

    The reason is the domain's own message, which names the offending field.
    The caller here is often the agent, and an error it cannot act on is an
    error it will retry unchanged, so the text is passed through rather than
    flattened into one generic sentence.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
