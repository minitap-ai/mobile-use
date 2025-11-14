"""
Example: Using the locked app feature to restrict task execution to a specific app.

This example demonstrates how to use the `with_locked_app_package()` method to ensure
that task execution remains within a specific application. This is useful for:
- Preventing the agent from navigating away from the target app
- Ensuring app-specific workflows stay focused
- Improving task reliability by maintaining app context

When an app is locked:
- The system ensures the app is open before starting
- If the app is accidentally closed or navigated away from, the Contextor agent
  will attempt to relaunch it
- The Planner and Cortex agents will prioritize in-app actions
"""

import asyncio

from minitap.mobile_use.sdk.agent import Agent


async def main():
    # Initialize agent
    agent = Agent()
    await agent.init()

    print("=" * 60)
    print("Example 1: Send a WhatsApp message, locked to WhatsApp")
    print("=" * 60)

    # Example 1: Send a WhatsApp message, locked to WhatsApp
    # The agent will stay within WhatsApp throughout the task
    result = await agent.run_task(
        request=agent.new_task("Send 'Hello!' to Alice")
        .with_locked_app_package("com.whatsapp")
        .build()
    )
    print(f"Result: {result}")

    print("\n" + "=" * 60)
    print("Example 2: Order food, locked to Uber Eats")
    print("=" * 60)

    # Example 2: Order food, locked to Uber Eats
    # The agent will remain in the Uber Eats app for the entire task
    result = await agent.run_task(
        request=agent.new_task("Order a pizza from my favorite restaurant")
        .with_locked_app_package("com.ubercab.eats")
        .build()
    )
    print(f"Result: {result}")

    print("\n" + "=" * 60)
    print("Example 3: Browse Safari on iOS, locked to Safari")
    print("=" * 60)

    # Example 3: iOS example - Browse Safari
    # Note: iOS uses bundle IDs instead of package names
    result = await agent.run_task(
        request=agent.new_task("Search for 'best coffee shops near me' in Safari")
        .with_locked_app_package("com.apple.mobilesafari")
        .build()
    )
    print(f"Result: {result}")

    print("\n" + "=" * 60)
    print("Example 4: Combining locked app with other builder methods")
    print("=" * 60)

    # Example 4: Combining locked app with other builder methods
    # You can chain multiple configuration methods together
    result = await agent.run_task(
        request=agent.new_task("Check my Instagram notifications")
        .with_locked_app_package("com.instagram.android")
        .with_max_steps(15)
        .with_trace_recording(enabled=True, path="./traces")
        .with_name("instagram-notifications-check")
        .build()
    )
    print(f"Result: {result}")

    # Cleanup
    await agent.clean()


if __name__ == "__main__":
    asyncio.run(main())
