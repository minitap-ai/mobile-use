from minitap.mobile_use.context import DevicePlatform, MobileUseContext
from minitap.mobile_use.controllers.android_controller import AndroidDeviceController
from minitap.mobile_use.controllers.device_controller import MobileDeviceController
from minitap.mobile_use.controllers.ios_controller import iOSDeviceController
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def create_device_controller(ctx: MobileUseContext) -> MobileDeviceController:
    platform = ctx.device.mobile_platform

    if platform == DevicePlatform.ANDROID:
        if ctx.adb_client is None:
            raise ValueError("ADB client not initialized for Android device")

        if ctx.ui_adb_client is None:
            raise ValueError("UIAutomator client not initialized for Android device")

        logger.info(f"Creating Android controller for device {ctx.device.device_id}")
        return AndroidDeviceController(
            device_id=ctx.device.device_id,
            adb_client=ctx.adb_client,
            ui_adb_client=ctx.ui_adb_client,
            device_width=ctx.device.device_width,
            device_height=ctx.device.device_height,
        )

    elif platform == DevicePlatform.IOS:
        if ctx.idb_client is None:
            raise ValueError("IDB client not initialized for iOS device")

        logger.info(f"Creating iOS controller for device {ctx.device.device_id}")
        return iOSDeviceController(
            idb_client=ctx.idb_client,
            device_width=ctx.device.device_width,
            device_height=ctx.device.device_height,
        )

    else:
        raise ValueError(f"Unsupported platform: {platform}")


def get_controller(ctx: MobileUseContext) -> MobileDeviceController:
    return create_device_controller(ctx)
