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


async def launch_app_with_retries(
    ctx: MobileUseContext,
    app_package: str,
    max_retries: int = 3,
) -> tuple[bool, str | None]:
    """
    Launch an app with retry logic and verification.

    Args:
        ctx: Mobile use context
        app_package: Package name (Android) or bundle ID (iOS) to launch
        max_retries: Maximum number of launch attempts (default: 3)

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
            continue

        await asyncio.sleep(2)

        current_package = get_current_foreground_package(ctx)
        logger.info(f"After launch attempt {attempt}, current foreground app: {current_package}")

        if current_package == app_package:
            logger.success(f"✅ Successfully launched app {app_package}")
            return True, None

        if attempt < max_retries:
            logger.warning(f"App not in foreground after launch attempt {attempt}, retrying...")

    current_package = get_current_foreground_package(ctx)
    error_msg = (
        f"Failed to launch {app_package} after {max_retries} attempts. "
        f'Current foreground app: "{current_package}"'
    )
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
