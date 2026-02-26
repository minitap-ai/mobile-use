"""
Factory functions for creating Limrun instances and controllers.

This module provides high-level functions to create and manage Limrun
Android and iOS instances using the Limrun Python SDK.
"""

import asyncio
import os
from enum import StrEnum

from limrun_api import AsyncLimrun
from limrun_api.types import AndroidInstance, IosInstance

from minitap.mobile_use.controllers.ios_controller import iOSDeviceController
from minitap.mobile_use.controllers.limrun_controller import (
    LimrunAndroidController,
    LimrunIosController,
)
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class LimrunPlatform(StrEnum):
    """Limrun device platform."""

    ANDROID = "android"
    IOS = "ios"


class LimrunInstanceConfig:
    """Configuration for creating a Limrun instance."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        inactivity_timeout: str = "10m",
        hard_timeout: str | None = None,
        display_name: str | None = None,
        labels: dict[str, str] | None = None,
    ):
        self.api_key = api_key or os.environ.get("MINITAP_API_KEY") or os.environ.get("LIM_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key is required. Set MINITAP_API_KEY or LIM_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.base_url = base_url or os.environ.get(
            "MINITAP_BASE_URL", "https://platform.minitap.ai"
        )
        self.inactivity_timeout = inactivity_timeout
        self.hard_timeout = hard_timeout
        self.display_name = display_name
        self.labels = labels or {}


async def create_limrun_android_instance(
    config: LimrunInstanceConfig,
) -> tuple[AndroidInstance, LimrunAndroidController]:
    """
    Create a Limrun Android instance and return the controller.

    Args:
        config: Configuration for the Limrun instance.

    Returns:
        Tuple of (AndroidInstance, LimrunAndroidController)

    Example:
        config = LimrunInstanceConfig(api_key="your-api-key")
        instance, controller = await create_limrun_android_instance(config)

        try:
            await controller.connect()
            screenshot = await controller.screenshot()
        finally:
            await controller.cleanup()
            await delete_limrun_android_instance(config, instance.metadata.id)
    """
    client = AsyncLimrun(api_key=config.api_key, base_url=f"{config.base_url}/api/v1/limrun")
    instance: AndroidInstance | IosInstance | None = None

    try:
        logger.info("Creating Limrun Android instance...")

        spec: dict = {
            "inactivityTimeout": config.inactivity_timeout,
        }
        if config.hard_timeout:
            spec["hardTimeout"] = config.hard_timeout

        metadata: dict = {}
        if config.display_name:
            metadata["displayName"] = config.display_name
        if config.labels:
            metadata["labels"] = config.labels

        instance = await client.android_instances.create(
            spec=spec,  # type: ignore[arg-type]
            metadata=metadata if metadata else None,  # type: ignore[arg-type]
            wait=True,
        )

        logger.info(f"Created Android instance: {instance.metadata.id}")

        instance = await _wait_for_instance_ready(
            client, instance.metadata.id, platform=LimrunPlatform.ANDROID
        )

        if not isinstance(instance, AndroidInstance):
            raise RuntimeError("Android instance missing adb_web_socket_url")

        if instance.status.adb_web_socket_url is None:
            raise RuntimeError("Android instance missing adb_web_socket_url")
        if instance.status.endpoint_web_socket_url is None:
            raise RuntimeError("Android instance missing endpoint_web_socket_url")

        controller = LimrunAndroidController(
            instance_id=instance.metadata.id,
            adb_ws_url=instance.status.adb_web_socket_url,
            endpoint_ws_url=instance.status.endpoint_web_socket_url,
            token=instance.status.token,
        )

        return instance, controller

    except Exception:
        if instance is not None:
            try:
                await client.android_instances.delete(instance.metadata.id)
                logger.warning(f"Cleaned up Android instance after failure: {instance.metadata.id}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to delete Android instance: {cleanup_error}")
        raise

    finally:
        await client.close()


async def create_limrun_ios_instance(
    config: LimrunInstanceConfig,
) -> tuple[IosInstance, iOSDeviceController, LimrunIosController]:
    """
    Create a Limrun iOS instance and return the controller.

    Args:
        config: Configuration for the Limrun instance.

    Returns:
        Tuple of (IosInstance, iOSDeviceController, LimrunIosController)

    Example:
        config = LimrunInstanceConfig(api_key="your-api-key")
        instance, controller = await create_limrun_ios_instance(config)

        try:
            await controller.connect()
            screenshot = await controller.screenshot()
        finally:
            await controller.cleanup()
            await delete_limrun_ios_instance(config, instance.metadata.id)
    """
    client = AsyncLimrun(api_key=config.api_key, base_url=f"{config.base_url}/api/v1/limrun")
    instance: AndroidInstance | IosInstance | None = None

    try:
        logger.info("Creating Limrun iOS instance...")

        spec: dict = {
            "inactivityTimeout": config.inactivity_timeout,
        }
        if config.hard_timeout:
            spec["hardTimeout"] = config.hard_timeout

        metadata: dict = {}
        if config.display_name:
            metadata["displayName"] = config.display_name
        if config.labels:
            metadata["labels"] = config.labels

        create_kwargs: dict = {"wait": True}
        if spec:
            create_kwargs["spec"] = spec
        if metadata:
            create_kwargs["metadata"] = metadata

        instance = await client.ios_instances.create(**create_kwargs)

        logger.info(f"Created iOS instance: {instance.metadata.id}")

        if instance.status.api_url is None:
            raise RuntimeError("iOS instance missing api_url")

        limrun_controller = LimrunIosController(
            instance_id=instance.metadata.id,
            api_url=instance.status.api_url,
            token=instance.status.token,
        )

        # Connect to get device dimensions
        await limrun_controller.connect()

        # Wrap in iOSDeviceController for unified interface
        controller = iOSDeviceController(
            ios_client=limrun_controller,
            device_id=instance.metadata.id,
            device_width=limrun_controller.device_width,
            device_height=limrun_controller.device_height,
        )

        return instance, controller, limrun_controller

    except Exception:
        if instance is not None:
            try:
                await client.ios_instances.delete(instance.metadata.id)
                logger.warning(f"Cleaned up iOS instance after failure: {instance.metadata.id}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to delete iOS instance: {cleanup_error}")
        raise

    finally:
        await client.close()


async def _wait_for_instance_ready(
    client: AsyncLimrun,
    instance_id: str,
    platform: LimrunPlatform,
    timeout: float = 120.0,
    poll_interval: float = 2.0,
) -> AndroidInstance | IosInstance:
    """Wait for a Limrun instance to be ready."""
    start_time = asyncio.get_event_loop().time()

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout:
            raise TimeoutError(
                f"Limrun {platform.value} instance {instance_id} did not become ready "
                f"within {timeout}s"
            )

        if platform == LimrunPlatform.ANDROID:
            instance = await client.android_instances.get(instance_id)
        else:
            instance = await client.ios_instances.get(instance_id)

        state = instance.status.state

        if state == "ready":
            logger.info(f"Limrun {platform.value} instance {instance_id} is ready")
            return instance

        if state == "terminated":
            error_msg = instance.status.error_message or "Unknown error"
            raise RuntimeError(
                f"Limrun {platform.value} instance {instance_id} terminated: {error_msg}"
            )

        logger.debug(
            f"Waiting for {platform.value} instance {instance_id} "
            f"(state: {state}, elapsed: {elapsed:.1f}s)"
        )
        await asyncio.sleep(poll_interval)


async def delete_limrun_android_instance(
    config: LimrunInstanceConfig,
    instance_id: str,
) -> None:
    """Delete a Limrun Android instance."""
    client = AsyncLimrun(api_key=config.api_key, base_url=f"{config.base_url}/api/v1/limrun")
    try:
        await client.android_instances.delete(instance_id)
        logger.info(f"Deleted Android instance: {instance_id}")
    finally:
        await client.close()


async def delete_limrun_ios_instance(
    config: LimrunInstanceConfig,
    instance_id: str,
) -> None:
    """Delete a Limrun iOS instance."""
    client = AsyncLimrun(api_key=config.api_key, base_url=f"{config.base_url}/api/v1/limrun")
    try:
        await client.ios_instances.delete(instance_id)
        logger.info(f"Deleted iOS instance: {instance_id}")
    finally:
        await client.close()


async def list_limrun_android_instances(
    config: LimrunInstanceConfig,
) -> list[AndroidInstance]:
    """List all Limrun Android instances."""
    client = AsyncLimrun(api_key=config.api_key, base_url=f"{config.base_url}/api/v1/limrun")
    try:
        page = await client.android_instances.list()
        return page.items
    finally:
        await client.close()


async def list_limrun_ios_instances(
    config: LimrunInstanceConfig,
) -> list[IosInstance]:
    """List all Limrun iOS instances."""
    client = AsyncLimrun(api_key=config.api_key, base_url=f"{config.base_url}/api/v1/limrun")
    try:
        page = await client.ios_instances.list()
        return page.items
    finally:
        await client.close()
