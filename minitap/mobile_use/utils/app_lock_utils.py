"""
Utilities for handling app locking and initial app launch logic.
"""

import asyncio

from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import launch_app
from minitap.mobile_use.controllers.platform_specific_commands_controller import (
    get_current_foreground_package,
)
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


async def _handle_initial_app_launch(
    ctx: MobileUseContext,
    locked_app_package: str | None,
) -> dict:
    """
    Handle initial app launch verification and launching if needed.

    If locked_app_package is set:
    1. Check if the app is already in the foreground
    2. If not, attempt to launch it (with retries)
    3. Return status dict with success/error information

    Args:
        ctx: Mobile use context
        locked_app_package: Package name (Android) or bundle ID (iOS) to lock to, or None

    Returns:
        Dictionary with keys:
        - locked_app_package: The package name (or None)
        - locked_app_initial_launch_success: True/False/None
        - locked_app_initial_launch_error: Error message or None
    """
    if locked_app_package is None:
        logger.info("No locked app package specified, skipping initial app launch")
        return {
            "locked_app_package": None,
            "locked_app_initial_launch_success": None,
            "locked_app_initial_launch_error": None,
        }

    logger.info(f"Starting initial app launch for package: {locked_app_package}")

    try:
        # Check if app is already in foreground
        current_package = get_current_foreground_package(ctx)
        logger.info(f"Current foreground app: {current_package}")

        if current_package and current_package.strip() == locked_app_package.strip():
            logger.info(f"App {locked_app_package} is already in foreground")
            return {
                "locked_app_package": locked_app_package,
                "locked_app_initial_launch_success": True,
                "locked_app_initial_launch_error": None,
            }

        # App is not in foreground, attempt to launch
        logger.info(f"App {locked_app_package} not in foreground, attempting to launch")
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            logger.info(f"Launch attempt {attempt}/{max_retries} for app {locked_app_package}")

            # Launch the app
            launch_result = launch_app(ctx, locked_app_package)
            if launch_result is not None:  # launch_app returns None on success
                error_msg = f"Failed to execute launch command for {locked_app_package}"
                logger.error(error_msg)
                if attempt == max_retries:
                    return {
                        "locked_app_package": locked_app_package,
                        "locked_app_initial_launch_success": False,
                        "locked_app_initial_launch_error": error_msg,
                    }
                continue

            # Wait 2 second for app to come to foreground
            await asyncio.sleep(2)

            # Verify app is in foreground
            current_package = get_current_foreground_package(ctx)
            logger.info(
                f"After launch attempt {attempt}, current foreground app: {current_package}"
            )

            if current_package and current_package.strip() == locked_app_package.strip():
                logger.info(
                    f"✅ Successfully launched and verified app {locked_app_package}"
                )
                return {
                    "locked_app_package": locked_app_package,
                    "locked_app_initial_launch_success": True,
                    "locked_app_initial_launch_error": None,
                }

            if attempt < max_retries:
                logger.warning(f"App not in foreground after launch attempt {attempt}, retrying...")

        # All retries exhausted
        error_msg = (
            f"Failed to launch {locked_app_package} after {max_retries} attempts. "
            f'Here is the actual foreground app: "{current_package}"'
        )
        logger.error(error_msg)
        return {
            "locked_app_package": locked_app_package,
            "locked_app_initial_launch_success": False,
            "locked_app_initial_launch_error": error_msg,
        }

    except Exception as e:
        error_msg = f"Exception during initial app launch: {str(e)}"
        logger.error(error_msg)
        return {
            "locked_app_package": locked_app_package,
            "locked_app_initial_launch_success": False,
            "locked_app_initial_launch_error": error_msg,
        }
