"""
Platform Usage - Minitap SDK with API Key Example

This example demonstrates how to use the mobile-use SDK via the Minitap platform:
- Agent with minitap_api_key
- PlatformTaskRequest with platform-provided task_id
- All task configuration (goal, output format, etc.) managed by platform UI

Platform Model:
- API key provides authentication and agent configuration
- task_id references pre-configured task from platform UI
- No goal, output_format, profile selection needed in code
- Everything bound to task_id + api_key combination

Run:
- python src/mobile_use/sdk/examples/platform_minimal_example.py
"""

import asyncio

from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import PlatformTaskRequest


async def main() -> None:
    """
    Main execution function demonstrating minitap platform usage pattern.

    Visit https://platform.minitap.ai to create a task, customize your profiles,
    and get your API key.
    """
    agent = Agent(
        minitap_api_key="your-api-key"
    )  # Optional, can be set with MINITAP_API_KEY environment variable
    agent.init()
    result = await agent.run_task(
        request=PlatformTaskRequest(
            task_id="your-task-id",
            profile="your-profile-name",
        )
    )
    print(result)
    agent.clean()


if __name__ == "__main__":
    asyncio.run(main())
