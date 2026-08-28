"""
Factory functions for creating cloud device instances and controllers.

This module adapts the cloud provider SDK to mobile-use controllers.
"""

import asyncio
import os
from enum import StrEnum

from limrun_api import AsyncLimrun
from limrun_api.types import AndroidInstance, IosInstance

from minitap.mobile_use.config import settings
from minitap.mobile_use.controllers.ios_controller import iOSDeviceController
from minitap.mobile_use.controllers.cloud_device_controller import (
    CloudAndroidController,
    CloudIosController,
)
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class ProviderPlatform(StrEnum):
    """Cloud provider device platform."""

    ANDROID = "android"
    IOS = "ios"


class CloudDeviceInstanceConfig:
    """Internal configuration for creating a cloud device instance."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        inactivity_timeout: str = "10m",
        hard_timeout: str | None = None,
        display_name: str | None = None,
        labels: dict[str, str] | None = None,
    ):
        self.api_key = api_key or os.environ.get("MINITAP_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key is required. Set MINITAP_API_KEY or pass the api_key parameter."
            )
        if base_url:
            self.base_url = f"{base_url.rstrip('/')}/api/v1"
        else:
            self.base_url = settings.MINITAP_API_BASE_URL.rstrip("/")
        self.inactivity_timeout = inactivity_timeout
        self.hard_timeout = hard_timeout
        self.display_name = display_name
        self.labels = labels or {}


def _build_cloud_client(config: CloudDeviceInstanceConfig) -> AsyncLimrun:
    return AsyncLimrun(api_key=config.api_key, base_url=f"{config.base_url}/limrun")


async def create_cloud_android_instance(
    config: CloudDeviceInstanceConfig,
) -> tuple[AndroidInstance, CloudAndroidController]:
    """
    Create a cloud Android instance and return the controller.

    Args:
        config: Cloud device configuration.

    Returns:
        Tuple of the provider instance and mobile-use controller.
    """
    client = _build_cloud_client(config)
    instance: AndroidInstance | IosInstance | None = None

    try:
        logger.info("Creating cloud Android instance...")

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
            client, instance.metadata.id, platform=ProviderPlatform.ANDROID
        )

        if not isinstance(instance, AndroidInstance):
            raise RuntimeError("Android instance missing adb_web_socket_url")

        if instance.status.adb_web_socket_url is None:
            raise RuntimeError("Android instance missing adb_web_socket_url")
        if instance.status.endpoint_web_socket_url is None:
            raise RuntimeError("Android instance missing endpoint_web_socket_url")

        controller = CloudAndroidController(
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


async def create_cloud_ios_instance(
    config: CloudDeviceInstanceConfig,
) -> tuple[IosInstance, iOSDeviceController, CloudIosController]:
    """
    Create a cloud iOS instance and return the controller.

    Args:
        config: Cloud device configuration.

    Returns:
        Tuple of the provider instance, unified controller, and provider controller.
    """
    client = _build_cloud_client(config)
    instance: AndroidInstance | IosInstance | None = None

    try:
        logger.info("Creating cloud iOS instance...")

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

        cloud_controller = CloudIosController(
            instance_id=instance.metadata.id,
            api_url=instance.status.api_url,
            token=instance.status.token,
        )

        # Connect to get device dimensions
        await cloud_controller.connect()

        # Wrap in iOSDeviceController for unified interface
        controller = iOSDeviceController(
            ios_client=cloud_controller,
            device_id=instance.metadata.id,
            device_width=cloud_controller.device_width,
            device_height=cloud_controller.device_height,
        )

        return instance, controller, cloud_controller

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
    platform: ProviderPlatform,
    timeout: float = 120.0,
    poll_interval: float = 2.0,
) -> AndroidInstance | IosInstance:
    """Wait for a cloud instance to be ready."""
    start_time = asyncio.get_event_loop().time()

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout:
            raise TimeoutError(
                f"Cloud {platform.value} instance {instance_id} did not become ready "
                f"within {timeout}s"
            )

        if platform == ProviderPlatform.ANDROID:
            instance = await client.android_instances.get(instance_id)
        else:
            instance = await client.ios_instances.get(instance_id)

        state = instance.status.state

        if state == "ready":
            logger.info(f"Cloud {platform.value} instance {instance_id} is ready")
            return instance

        if state == "terminated":
            error_msg = instance.status.error_message or "Unknown error"
            raise RuntimeError(
                f"Cloud {platform.value} instance {instance_id} terminated: {error_msg}"
            )

        logger.debug(
            f"Waiting for {platform.value} instance {instance_id} "
            f"(state: {state}, elapsed: {elapsed:.1f}s)"
        )
        await asyncio.sleep(poll_interval)


async def delete_cloud_android_instance(
    config: CloudDeviceInstanceConfig,
    instance_id: str,
) -> None:
    """Delete a cloud Android instance."""
    client = _build_cloud_client(config)
    try:
        await client.android_instances.delete(instance_id)
        logger.info(f"Deleted Android instance: {instance_id}")
    finally:
        await client.close()


async def delete_cloud_ios_instance(
    config: CloudDeviceInstanceConfig,
    instance_id: str,
) -> None:
    """Delete a cloud iOS instance."""
    client = _build_cloud_client(config)
    try:
        await client.ios_instances.delete(instance_id)
        logger.info(f"Deleted iOS instance: {instance_id}")
    finally:
        await client.close()


async def list_cloud_android_instances(
    config: CloudDeviceInstanceConfig,
) -> list[AndroidInstance]:
    """List all cloud Android instances."""
    client = _build_cloud_client(config)
    try:
        page = await client.android_instances.list()
        return page.items
    finally:
        await client.close()


async def list_cloud_ios_instances(
    config: CloudDeviceInstanceConfig,
) -> list[IosInstance]:
    """List all cloud iOS instances."""
    client = _build_cloud_client(config)
    try:
        page = await client.ios_instances.list()
        return page.items
    finally:
        await client.close()
