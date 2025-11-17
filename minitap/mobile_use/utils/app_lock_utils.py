"""
Utilities for handling app locking and initial app launch logic.
"""

import asyncio

from minitap.mobile_use.context import AppLaunchResult, MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import launch_app
from minitap.mobile_use.controllers.platform_specific_commands_controller import (
    get_current_foreground_package,
)
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


async def _poll_for_app_ready(
    ctx: MobileUseContext,
    app_package: str,
    max_poll_seconds: int = 15,
    poll_interval: float = 1.0,
) -> tuple[bool, str | None]:
    """
    Poll for app to be ready after launch.

    Treats mCurrentFocus=null as a loading state and keeps polling.
    Only fails if we get a different (non-null) package or timeout.

    Args:
        ctx: Mobile use context
        app_package: Expected package name
        max_poll_seconds: Maximum time to poll (default: 15s)
        poll_interval: Time between polls (default: 1s)

    Returns:
        Tuple of (success: bool, error_message: str | None)
    """
    polls = int(max_poll_seconds / poll_interval)

    for i in range(polls):
        current_package = get_current_foreground_package(ctx)

        if current_package == app_package:
            logger.success(f"App {app_package} is ready (took ~{i * poll_interval:.1f}s)")
            return True, None

        if current_package is None:
            logger.debug(f"Poll {i + 1}/{polls}: App loading (mCurrentFocus=null)...")
        else:
            error_msg = (
                f"Wrong app in foreground: expected '{app_package}', got '{current_package}'"
            )
            logger.warning(error_msg)
            return False, error_msg

        if i < polls - 1:
            await asyncio.sleep(poll_interval)

    current_package = get_current_foreground_package(ctx)
    error_msg = (
        f"Timeout waiting for {app_package} to load after {max_poll_seconds}s. "
        f"Current foreground: {current_package}"
    )
    logger.error(error_msg)
    return False, error_msg


async def launch_app_with_retries(
    ctx: MobileUseContext,
    app_package: str,
    max_retries: int = 3,
    max_poll_seconds: int = 15,
) -> tuple[bool, str | None]:
    """
    Launch an app with retry logic and smart polling.

    Args:
        ctx: Mobile use context
        app_package: Package name (Android) or bundle ID (iOS) to launch
        max_retries: Maximum number of launch attempts (default: 3)
        max_poll_seconds: Maximum time to wait for app to load per attempt (default: 15s)

    Returns:
        Tuple of (success: bool, error_message: str | None)
    """
    for attempt in range(1, max_retries + 1):
        logger.info(f"Launch attempt {attempt}/{max_retries} for app {app_package}")

        launch_result = launch_app(ctx, app_package)
        if launch_result is not None:
            error_msg = f"Failed to execute launch command for {app_package}: {launch_result}"
            logger.error(error_msg)
            if attempt == max_retries:
                return False, error_msg
            await asyncio.sleep(2)
            continue

        await asyncio.sleep(1)

        success, error_msg = await _poll_for_app_ready(ctx, app_package, max_poll_seconds)

        if success:
            return True, None

        if attempt < max_retries:
            logger.warning(f"Attempt {attempt} failed: {error_msg}. Retrying...")
            await asyncio.sleep(1)

    error_msg = f"Failed to launch {app_package} after {max_retries} attempts"
    logger.error(error_msg)
    return False, error_msg


async def _handle_initial_app_launch(
    ctx: MobileUseContext,
    locked_app_package: str,
) -> AppLaunchResult:
    """
    Handle initial app launch verification and launching if needed.

    If locked_app_package is set:
    1. Check if the app is already in the foreground
    2. If not, attempt to launch it (with retries)
    3. Return status with success/error information

    Args:
        ctx: Mobile use context
        locked_app_package: Package name (Android) or bundle ID (iOS) to lock to, or None

    Returns:
        AppLaunchResult with launch status and error information
    """

    logger.info(f"Starting initial app launch for package: {locked_app_package}")

    try:
        current_package = get_current_foreground_package(ctx)
        logger.info(f"Current foreground app: {current_package}")

        if current_package == locked_app_package:
            logger.info(f"App {locked_app_package} is already in foreground")
            return AppLaunchResult(
                locked_app_package=locked_app_package,
                locked_app_initial_launch_success=True,
                locked_app_initial_launch_error=None,
            )

        logger.info(f"App {locked_app_package} not in foreground, attempting to launch")
        success, error_msg = await launch_app_with_retries(ctx, locked_app_package)

        return AppLaunchResult(
            locked_app_package=locked_app_package,
            locked_app_initial_launch_success=success,
            locked_app_initial_launch_error=error_msg,
        )

    except Exception as e:
        error_msg = f"Exception during initial app launch: {str(e)}"
        logger.error(error_msg)
        return AppLaunchResult(
            locked_app_package=locked_app_package,
            locked_app_initial_launch_success=False,
            locked_app_initial_launch_error=error_msg,
        )
