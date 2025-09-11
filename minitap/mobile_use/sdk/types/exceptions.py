"""
Exceptions for the Mobile-use SDK.

This module defines the exception hierarchy used throughout the Mobile-use SDK.
"""


class MobileUseError(Exception):
    """Base exception class for all Mobile-use SDK exceptions."""

    def __init__(self, message="An error occurred in the Mobile-use SDK"):
        self.message = message
        super().__init__(self.message)


class DeviceError(MobileUseError):
    """Exception raised for errors related to mobile devices."""

    def __init__(self, message="A device-related error occurred"):
        super().__init__(message)


class DeviceNotFoundError(DeviceError):
    """Exception raised when no mobile device is found."""

    def __init__(self, message="No mobile device found"):
        super().__init__(message)


class ServerError(MobileUseError):
    """Exception raised for errors related to Mobile-use servers."""

    def __init__(self, message="A server-related error occurred"):
        super().__init__(message)


class ServerStartupError(ServerError):
    """Exception raised when Mobile-use servers fail to start."""

    def __init__(self, server_name=None, message=None):
        if server_name and not message:
            message = f"Failed to start {server_name}"
        elif not message:
            message = "Failed to start Mobile-use servers"
        super().__init__(message)
        self.server_name = server_name


class AgentError(MobileUseError):
    """Exception raised for errors related to the Mobile-use agent."""

    def __init__(self, message="An agent-related error occurred"):
        super().__init__(message)


class AgentNotInitializedError(AgentError):
    """Exception raised when attempting operations on an uninitialized agent."""

    def __init__(self, message="Agent is not initialized. Call init() first"):
        super().__init__(message)


class AgentTaskRequestError(AgentError):
    """Exception raised when a requested task is invalid."""

    def __init__(self, message="An agent task-related error occurred"):
        super().__init__(message)


class AgentProfileNotFoundError(AgentTaskRequestError):
    """Exception raised when an agent profile is not found."""

    def __init__(self, profile_name: str):
        super().__init__(f"Agent profile {profile_name} not found")


class ExecutableNotFoundError(MobileUseError):
    """Exception raised when a required executable is not found."""

    def __init__(self, executable_name: str):
        install_instructions = {
            "adb": "https://developer.android.com/tools/adb",
            "maestro": "https://docs.maestro.dev/getting-started/installing-maestro",
        }
        message = f"Required executable '{executable_name}' not found in PATH."
        if executable_name in install_instructions:
            message += f"\nTo install it, please visit: {install_instructions[executable_name]}"
        super().__init__(message)
