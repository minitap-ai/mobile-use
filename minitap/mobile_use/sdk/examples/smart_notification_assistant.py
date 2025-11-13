"""
Smart Notification Assistant - Intermediate SDK Usage Example

This example demonstrates more advanced SDK features including:
- TaskRequestBuilder pattern
- Multiple agent profiles for different reasoning tasks
- Tracing for debugging/visualization
- Structured output with Pydantic
- Exception handling

It performs a practical automation task:
1. Checks notification panel for unread notifications
2. Categorizes them by priority/app
3. Performs actions based on notification content

Run:
- python src/mobile_use/sdk/examples/smart_notification_assistant.py
"""

import asyncio
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from minitap.mobile_use.config import LLM, LLMConfig, LLMConfigUtils, LLMWithFallback
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import Builders
from minitap.mobile_use.sdk.types import AgentProfile
from minitap.mobile_use.sdk.types.exceptions import AgentError


class NotificationPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Notification(BaseModel):
    """Individual notification details."""

    app_name: str = Field(..., description="Name of the app that sent the notification")
    title: str = Field(..., description="Title/header of the notification")
    message: str = Field(..., description="Message content of the notification")
    priority: NotificationPriority = Field(
        default=NotificationPriority.MEDIUM, description="Priority level of notification"
    )


class NotificationSummary(BaseModel):
    """Summary of all notifications."""

    total_count: int = Field(..., description="Total number of notifications found")
    high_priority_count: int = Field(0, description="Count of high priority notifications")
    notifications: list[Notification] = Field(
        default_factory=list, description="List of individual notifications"
    )


def get_agent() -> Agent:
    # Create two specialized profiles:
    # 1. An analyzer profile for detailed inspection tasks
    analyzer_profile = AgentProfile(
        name="analyzer",
        llm_config=LLMConfig(
            planner=LLMWithFallback(
                provider="openrouter",
                model="meta-llama/llama-4-scout",
                fallback=LLM(provider="openrouter", model="meta-llama/llama-4-maverick"),
            ),
            orchestrator=LLMWithFallback(
                provider="openrouter",
                model="meta-llama/llama-4-scout",
                fallback=LLM(provider="openrouter", model="meta-llama/llama-4-maverick"),
            ),
            contextor=LLMWithFallback(
                provider="openrouter",
                model="meta-llama/llama-4-scout",
                fallback=LLM(provider="openrouter", model="meta-llama/llama-4-maverick"),
            ),
            cortex=LLMWithFallback(
                provider="openai",
                model="o4-mini",
                fallback=LLM(provider="openai", model="gpt-5"),
            ),
            screen_analyzer=LLMWithFallback(
                provider="openai",
                model="gpt-4o",
                fallback=LLM(provider="openai", model="gpt-5-nano"),
            ),
            executor=LLMWithFallback(
                provider="openai",
                model="gpt-5-nano",
                fallback=LLM(provider="openai", model="gpt-5-mini"),
            ),
            utils=LLMConfigUtils(
                outputter=LLMWithFallback(
                    provider="openai",
                    model="gpt-5-nano",
                    fallback=LLM(provider="openai", model="gpt-5-mini"),
                ),
                hopper=LLMWithFallback(
                    provider="openai",
                    model="gpt-5-nano",
                    fallback=LLM(provider="openai", model="gpt-5-mini"),
                ),
            ),
        ),
        # from_file="/tmp/analyzer.jsonc"  # can be loaded from file
    )

    # 2. An action profile for handling easy & fast actions based on notifications
    action_profile = AgentProfile(
        name="note_taker",
        llm_config=LLMConfig(
            planner=LLMWithFallback(
                provider="openai", model="o3", fallback=LLM(provider="openai", model="gpt-5")
            ),
            orchestrator=LLMWithFallback(
                provider="google",
                model="gemini-2.5-flash",
                fallback=LLM(provider="openai", model="gpt-5"),
            ),
            contextor=LLMWithFallback(
                provider="openai",
                model="gpt-5-nano",
                fallback=LLM(provider="openai", model="gpt-5-mini"),
            ),
            cortex=LLMWithFallback(
                provider="openai",
                model="o4-mini",
                fallback=LLM(provider="openai", model="gpt-5"),
            ),
            screen_analyzer=LLMWithFallback(
                provider="openai",
                model="gpt-4o",
                fallback=LLM(provider="openai", model="gpt-5-nano"),
            ),
            executor=LLMWithFallback(
                provider="openai",
                model="gpt-4o-mini",
                fallback=LLM(provider="openai", model="gpt-5-nano"),
            ),
            utils=LLMConfigUtils(
                outputter=LLMWithFallback(
                    provider="openai",
                    model="gpt-5-nano",
                    fallback=LLM(provider="openai", model="gpt-5-mini"),
                ),
                hopper=LLMWithFallback(
                    provider="openai",
                    model="gpt-5-nano",
                    fallback=LLM(provider="openai", model="gpt-5-mini"),
                ),
            ),
        ),
    )

    # Configure default task settings with tracing
    task_defaults = Builders.TaskDefaults.with_max_steps(200).build()

    # Configure the agent
    config = (
        Builders.AgentConfig.add_profiles(profiles=[analyzer_profile, action_profile])
        .with_default_profile(profile=action_profile)
        .with_default_task_config(config=task_defaults)
        .build()
    )
    return Agent(config=config)


async def main():
    # Set up traces directory with timestamp for uniqueness
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    traces_dir = f"/tmp/notification_traces/{timestamp}"
    agent = get_agent()

    try:
        # Initialize agent (finds a device, starts required servers)
        await agent.init()

        print("Checking for notifications...")

        # Task 1: Get and analyze notifications with analyzer profile
        notification_task = (
            agent.new_task(
                goal="Open the notification panel (swipe down from top). "
                "Scroll through the first 3 unread notifications. "
                "For each notification, identify the app name, title, and content. "
                "Tag messages from messaging apps or email as high priority."
            )
            .with_output_format(NotificationSummary)
            .using_profile("analyzer")
            .with_name("notification_scan")
            .with_max_steps(400)
            .with_trace_recording(enabled=True, path=traces_dir)
            .build()
        )

        # Execute the task with proper exception handling
        try:
            notifications = await agent.run_task(request=notification_task)

            # Display the structured results
            if notifications:
                print("\n=== Notification Summary ===")
                print(f"Total notifications: {notifications.total_count}")
                print(f"High priority: {notifications.high_priority_count}")

                # Task 2: Create a note to store the notification summary
                response = await agent.run_task(
                    goal="Open my Notes app and create a new note summarizing the following "
                    f"information:\n{notifications}",
                    name="email_action",
                    profile="note_taker",
                )
                print(f"Action result: {response}")

            else:
                print("Failed to retrieve notifications")

        except AgentError as e:
            print(f"Agent error occurred: {e}")
        except Exception as e:
            print(f"Unexpected error: {type(e).__name__}: {e}")
            raise

    finally:
        # Clean up
        await agent.clean()
        print(f"\nTraces saved to: {traces_dir}")


if __name__ == "__main__":
    asyncio.run(main())
