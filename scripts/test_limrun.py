"""
Test script for Limrun iOS controller.

Usage:
    1. Create a .env file with LIM_API_KEY=your-api-key
    2. python scripts/test_limrun.py
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from minitap.mobile_use.clients.limrun_factory import (
    LimrunInstanceConfig,
    create_limrun_ios_instance,
    delete_limrun_ios_instance,
)
from minitap.mobile_use.controllers.types import CoordinatesSelectorRequest
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import Builders
from minitap.mobile_use.sdk.types import LimrunPlatform

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
        if screenshot_b64:
            screenshot_path.write_bytes(screenshot_b64)
            print(f"Screenshot saved to: {screenshot_path}")

        print("Getting raw accessibility data...")
        raw_data = await controller.describe_all()
        print(f"Raw data has {len(raw_data)} elements")
        if raw_data:
            print(f"Sample raw element keys: {list(raw_data[0].keys())}")
            print(f"Sample raw element: {raw_data[0]}")

        print("\nGetting UI hierarchy...")
        hierarchy = await controller.get_ui_hierarchy()
        print(f"Found {len(hierarchy)} UI elements")
        # Print first 10 elements with labels
        for i, elem in enumerate(hierarchy[:10]):
            label = elem.get("label", "")
            value = elem.get("value", "")
            print(f"  [{i}] type={elem.get('type')}, label={label}, value={value}")

        print("Current app:", await controller.app_current())

        print("Pressing home button...")
        await controller.press_home()

        print("Launching Settings app...")
        await controller.launch_app("com.apple.Preferences")
        await asyncio.sleep(2)

        print("Taking another screenshot...")
        screenshot_b64 = await controller.screenshot()
        screenshot_path = Path("limrun_screenshot_settings.png")
        if screenshot_b64:
            screenshot_path.write_bytes(screenshot_b64)
            print(f"Screenshot saved to: {screenshot_path}")

        print("Current app:", await controller.app_current())

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


async def main2():
    # Configure agent with limrun device
    config = Builders.AgentConfig.for_limrun(LimrunPlatform.IOS).build()  # or LimrunPlatform.IOS

    agent = Agent(config=config)
    await agent.init()  # Provisions limrun device automatically

    try:
        await agent.run_task(
            goal="Open settings app, find the apps section, tap on it and search for Reddit"
        )
    finally:
        await agent.clean()  # Cleans up limrun device automatically


if __name__ == "__main__":
    asyncio.run(main2())
