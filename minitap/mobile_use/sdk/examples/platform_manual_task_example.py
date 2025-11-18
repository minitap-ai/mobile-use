"""
Platform Usage - Manual Task Creation Example

This example demonstrates how to use the mobile-use SDK with manual task creation:
- Agent with minitap_api_key
- PlatformTaskRequest with ManualTaskConfig instead of task_id
- Task configuration provided directly in code (goal, output_description)
- No need to pre-create task in platform UI

Platform Model:
- API key provides authentication and agent configuration
- ManualTaskConfig creates task on-the-fly with:
  - max_steps: 400 (fixed)
  - enable_remote_tracing: True (fixed)
  - profile: "default" (fixed)
  - goal: provided by you
  - output_description: provided by you (optional)

Run:
- python src/mobile_use/sdk/examples/platform_manual_task_example.py
"""

import asyncio

from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import ManualTaskConfig, PlatformTaskRequest


async def main() -> None:
    """
    Main execution function demonstrating manual task creation pattern.

    Visit https://platform.minitap.ai to get your API key.
    Set MINITAP_API_KEY and MINITAP_BASE_URL environment variables.
    """
    agent = Agent()
    await agent.init()

    # Example 1: Simple manual task
    result = await agent.run_task(
        request=PlatformTaskRequest(
            task=ManualTaskConfig(
                goal="Open the settings app and tell me the battery level",
            ),
            profile="default",  # Optional, defaults to "default"
        )
    )
    print("Result 1:", result)

    # Example 2: Manual task with output description
    result = await agent.run_task(
        request=PlatformTaskRequest(
            task=ManualTaskConfig(
                goal="Find the first 3 unread emails in Gmail",
                output_description="A JSON array with sender and subject for each email",
            ),
        ),
        # Lock gmail to ensure it is automatically started and locked during task execution
        locked_app_package="com.google.android.gm",
    )
    print("Result 2:", result)

    await agent.clean()


if __name__ == "__main__":
    asyncio.run(main())
