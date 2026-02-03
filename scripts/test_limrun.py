"""
Test script for Limrun iOS controller.

Usage:
    1. Create a .env file with LIM_API_KEY=your-api-key
    2. python scripts/test_limrun.py
"""

import asyncio
import base64
import os
from pathlib import Path

from dotenv import load_dotenv

from minitap.mobile_use.clients.limrun_factory import (
    LimrunInstanceConfig,
    create_limrun_ios_instance,
    delete_limrun_ios_instance,
)
from minitap.mobile_use.controllers.types import CoordinatesSelectorRequest

load_dotenv()


async def main():
    api_key = os.getenv("MINITAP_API_KEY") or os.getenv("LIM_API_KEY")
    if not api_key:
        print("Error: MINITAP_API_KEY or LIM_API_KEY environment variable is not set")
        print("Set MINITAP_API_KEY for Minitap proxy, or LIM_API_KEY for direct Limrun")
        return

    base_url = os.getenv("MINITAP_BASE_URL")

    print("Creating Limrun iOS instance...")
    config = LimrunInstanceConfig(
        api_key=api_key,
        base_url=base_url,
        inactivity_timeout="10m",
    )

    instance, controller = await create_limrun_ios_instance(config)
    print(f"Instance created: {instance.metadata.id}")

    try:
        print("Connecting to device...")
        await controller.connect()
        print(f"Connected! Device: {controller.device_width}x{controller.device_height}")

        print("Taking screenshot...")
        screenshot_b64 = await controller.screenshot()
        screenshot_path = Path("limrun_screenshot.png")
        screenshot_path.write_bytes(base64.b64decode(screenshot_b64))
        print(f"Screenshot saved to: {screenshot_path}")

        print("Getting UI hierarchy...")
        hierarchy = await controller.get_ui_hierarchy()
        print(f"Found {len(hierarchy)} UI elements")

        print("Pressing home button...")
        await controller.press_home()

        print("Launching Settings app...")
        await controller.launch_app("com.apple.Preferences")
        await asyncio.sleep(2)

        print("Taking another screenshot...")
        screenshot_b64 = await controller.screenshot()
        screenshot_path = Path("limrun_screenshot_settings.png")
        screenshot_path.write_bytes(base64.b64decode(screenshot_b64))
        print(f"Screenshot saved to: {screenshot_path}")

        print("Tapping at coordinates (200, 300)...")
        result = await controller.tap(CoordinatesSelectorRequest(x=200, y=300))
        if result.error:
            print(f"Tap error: {result.error}")
        else:
            print("Tap successful")

        print("\nTest completed successfully!")

    except Exception as e:
        print(f"Error during test: {e}")
        raise

    finally:
        print("Cleaning up...")
        await controller.cleanup()
        await delete_limrun_ios_instance(config, instance.metadata.id)
        print("Instance deleted")


if __name__ == "__main__":
    asyncio.run(main())
