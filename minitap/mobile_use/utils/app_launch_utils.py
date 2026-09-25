"""
Utilities for handling app locking and initial app launch logic.
"""

import asyncio

from minitap.mobile_use.context import AppLaunchResult, AppLockPolicy, MobileUseContext
from minitap.mobile_use.controllers.platform_specific_commands_controller import (
    get_current_foreground_package_async,
)
from minitap.mobile_use.errors import AppLockViolationError
from minitap.mobile_use.utils.app_lock_events import record_app_lock_event
from minitap.mobile_use.controllers.unified_controller import UnifiedMobileController
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
        current_package = await get_current_foreground_package_async(ctx)

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

    current_package = await get_current_foreground_package_async(ctx)
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

        controller = UnifiedMobileController(ctx)
        launch_success = await controller.launch_app(app_package)
        if not launch_success:
            error_msg = f"Failed to execute launch command for {app_package}"
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


def get_strict_locked_app_package(ctx: MobileUseContext) -> str | None:
    """Return the approved package only when strict enforcement is enabled."""

    execution_setup = getattr(ctx, "execution_setup", None)
    app_lock_status = getattr(execution_setup, "app_lock_status", None)
    if not app_lock_status or app_lock_status.app_lock_policy != "strict":
        return None
    return app_lock_status.locked_app_package


def assert_strict_app_launch_allowed(ctx: MobileUseContext, app_package: str) -> None:
    """Reject an executor request to launch an app outside a strict boundary."""

    locked_app_package = get_strict_locked_app_package(ctx)
    if locked_app_package and app_package != locked_app_package:
        record_app_lock_event(
            locked_app_package=locked_app_package,
            action="launch_app",
            decision="blocked",
            reason="launch_other_app",
            target_package=app_package,
        )
        raise AppLockViolationError(
            f"Strict app lock only allows {locked_app_package}; refusing to launch {app_package}"
        )


async def enforce_strict_app_lock(ctx: MobileUseContext) -> bool:
    """Verify the foreground package after an action and restore it if needed.

    Returns ``True`` when a deterministic relaunch was required.  It raises
    rather than producing a warning if the foreground app is unknown or the
    approved app cannot be restored.  Callers use this after each executor tool
    call so a batch cannot continue operating in an unintended application.
    """

    locked_app_package = get_strict_locked_app_package(ctx)
    if not locked_app_package:
        return False

    execution_setup = getattr(ctx, "execution_setup", None)
    app_lock_status = getattr(execution_setup, "app_lock_status", None)
    if app_lock_status is None or app_lock_status.locked_app_initial_launch_success is not True:
        record_app_lock_event(
            locked_app_package=locked_app_package,
            action="foreground_check",
            decision="aborted",
            reason="initial_launch_unverified",
        )
        raise AppLockViolationError(
            f"Strict app lock could not verify initial launch of {locked_app_package}"
        )

    current_app_package = await get_current_foreground_package_async(ctx)
    if current_app_package == locked_app_package:
        return False
    if current_app_package is None:
        record_app_lock_event(
            locked_app_package=locked_app_package,
            action="foreground_check",
            decision="aborted",
            reason="foreground_unknown",
        )
        raise AppLockViolationError(
            f"Could not verify strict app lock for {locked_app_package}: foreground app is unknown"
        )

    logger.warning(
        f"Strict app lock observed {current_app_package} instead of {locked_app_package}; "
        "restoring the approved app"
    )
    success, error = await launch_app_with_retries(ctx, app_package=locked_app_package)
    verified_package = await get_current_foreground_package_async(ctx) if success else None
    if verified_package != locked_app_package:
        record_app_lock_event(
            locked_app_package=locked_app_package,
            action="foreground_check",
            decision="aborted",
            reason="restore_failed",
            target_package=current_app_package,
        )
        if not success:
            raise AppLockViolationError(
                f"Strict app lock could not restore {locked_app_package}: "
                f"{error or 'foreground verification failed'}"
            )
        raise AppLockViolationError(
            f"Could not verify strict app lock for {locked_app_package} after relaunch"
        )
    record_app_lock_event(
        locked_app_package=locked_app_package,
        action="foreground_check",
        decision="restored",
        reason="foreground_mismatch",
        target_package=current_app_package,
    )
    return True


async def _handle_initial_app_launch(
    ctx: MobileUseContext,
    locked_app_package: str,
    app_lock_policy: AppLockPolicy = "permissive",
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
    if not locked_app_package:
        error_msg = f"Invalid locked_app_package: '{locked_app_package}'"
        logger.error(error_msg)
        return AppLaunchResult(
            locked_app_package=locked_app_package,
            locked_app_initial_launch_success=False,
            locked_app_initial_launch_error=error_msg,
            app_lock_policy=app_lock_policy,
        )

    logger.info(f"Starting initial app launch for package: {locked_app_package}")

    try:
        current_package = await get_current_foreground_package_async(ctx)
        logger.info(f"Current foreground app: {current_package}")

        if current_package == locked_app_package:
            logger.info(f"App {locked_app_package} is already in foreground")
            return AppLaunchResult(
                locked_app_package=locked_app_package,
                locked_app_initial_launch_success=True,
                locked_app_initial_launch_error=None,
                app_lock_policy=app_lock_policy,
            )

        logger.info(f"App {locked_app_package} not in foreground, attempting to launch")
        success, error_msg = await launch_app_with_retries(ctx, locked_app_package)

        return AppLaunchResult(
            locked_app_package=locked_app_package,
            locked_app_initial_launch_success=success,
            locked_app_initial_launch_error=error_msg,
            app_lock_policy=app_lock_policy,
        )

    except Exception as e:
        error_msg = f"Exception during initial app launch: {str(e)}"
        logger.error(error_msg)
        return AppLaunchResult(
            locked_app_package=locked_app_package,
            locked_app_initial_launch_success=False,
            locked_app_initial_launch_error=error_msg,
            app_lock_policy=app_lock_policy,
        )
