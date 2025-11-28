"""Test script to debug IDB screenshot and accessibility hierarchy."""

import asyncio
import os
import time

from minitap.mobile_use.clients.idb_client import IdbClientWrapper


async def test_idb():
    udid = os.getenv("IOS_UDID", "8EDAF7E4-5924-44B0-8126-5659EE079359")

    print(f"Creating IDB client for device: {udid}")
    idb = IdbClientWrapper(udid=udid)

    try:
        print("Initializing companion...")
        start = time.time()
        success = await idb.init_companion()
        print(f"Companion init: {success} ({time.time() - start:.2f}s)")

        if not success:
            print("Failed to initialize companion, exiting")
            return

        # Test screenshot
        print("\n--- Testing screenshot (IDB) ---")
        start = time.time()
        try:
            screenshot_bytes = await asyncio.wait_for(
                idb.screenshot(),  # type: ignore
                timeout=10.0,
            )
            if screenshot_bytes:
                print(f"Screenshot: {len(screenshot_bytes)} bytes ({time.time() - start:.2f}s)")
            else:
                print(f"Screenshot returned None ({time.time() - start:.2f}s)")
        except TimeoutError:
            print("Screenshot TIMEOUT after 10s")
        except Exception as e:
            print(f"Screenshot error: {e}")

        # Test describe_all (accessibility hierarchy)
        print("\n--- Testing describe_all (accessibility hierarchy via IDB) ---")
        start = time.time()
        try:
            hierarchy = await asyncio.wait_for(
                idb.describe_all(),  # type: ignore
                timeout=10,
            )
            if hierarchy:
                print(f"Hierarchy received: {type(hierarchy)} ({time.time() - start:.2f}s)")
                if isinstance(hierarchy, dict):
                    print(f"  Top-level keys: {list(hierarchy.keys())}")
            else:
                print(f"Hierarchy returned None ({time.time() - start:.2f}s)")
        except TimeoutError:
            print("describe_all TIMEOUT after 10s")
        except Exception as e:
            print(f"describe_all error: {e}")

    finally:
        print("\n--- Cleanup ---")
        await idb.cleanup()
        print("Done")


if __name__ == "__main__":
    asyncio.run(test_idb())
