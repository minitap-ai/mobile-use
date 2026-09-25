"""Lightweight errors shared by the SDK and execution graph."""


class MobileUseError(Exception):
    """Base exception class for all Mobile-use SDK errors."""

    def __init__(self, message="An error occurred in the Mobile-use SDK"):
        self.message = message
        super().__init__(self.message)


class AgentError(MobileUseError):
    """Exception raised for errors related to the Mobile-use agent."""

    def __init__(self, message="An agent-related error occurred"):
        super().__init__(message)


class AppLockViolationError(AgentError):
    """Raised when a strict app lock cannot be verified or enforced."""

    def __init__(self, message="Strict app lock blocked the task"):
        super().__init__(message)
