# Examples & Tutorials

This page provides practical examples and tutorials for using the mobile-use SDK.

### Simple Photo Organizer

This example demonstrates a straightforward way to use the mobile-use SDK without builders or advanced configuration. It performs a real-world automation task:

1. Opens the photo gallery
2. Finds photos from a specific date
3. Creates an album and moves those photos into it

```python
import asyncio
from datetime import date, timedelta
from pydantic import BaseModel, Field
from minitap.mobile_use.sdk import Agent


class PhotosResult(BaseModel):
    """Structured result from photo search."""

    found_photos: int = Field(..., description="Number of photos found")
    date_range: str = Field(..., description="Date range of photos found")
    album_created: bool = Field(..., description="Whether an album was created")
    album_name: str = Field(..., description="Name of the created album")
    photos_moved: int = Field(0, description="Number of photos moved to the album")


async def main() -> None:
    # Create a simple agent with default configuration
    agent = Agent()

    try:
        # Initialize agent (finds a device, starts required servers)
        agent.init()

        # Calculate yesterday's date for the example
        yesterday = date.today() - timedelta(days=1)
        formatted_date = yesterday.strftime("%B %d")  # e.g. "August 22"

        print(f"Looking for photos from {formatted_date}...")

        # First task: search for photos and organize them, with typed output
        result = await agent.run_task(
            goal=(
                f"Open the Photos/Gallery app. Find photos taken on {formatted_date}. "
                f"Create a new album named '{formatted_date} Memories' and "
                f"move those photos into it. Count how many photos were moved."
            ),
            output=PhotosResult,
            name="organize_photos",
        )

        # Handle and display the result
        if result:
            print("\n=== Photo Organization Complete ===")
            print(f"Found: {result.found_photos} photos from {result.date_range}")

            if result.album_created:
                print(f"Created album: '{result.album_name}'")
                print(f"Moved {result.photos_moved} photos to the album")
            else:
                print("No album was created")
        else:
            print("Failed to organize photos")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Always clean up resources
        agent.clean()


if __name__ == "__main__":
    asyncio.run(main())
```

### Smart Notification Assistant

This example demonstrates more advanced SDK features including:

* TaskRequestBuilder pattern
* Multiple agent profiles for different reasoning tasks
* Tracing for debugging/visualization
* Structured output with Pydantic
* Exception handling

It performs a practical automation task:

1. Checks notification panel for unread notifications
2. Categorizes them by priority/app
3. Performs actions based on notification content

```python
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
            planner=LLM(provider="openrouter", model="meta-llama/llama-4-scout"),
            orchestrator=LLM(provider="openrouter", model="meta-llama/llama-4-scout"),
            cortex=LLMWithFallback(
                provider="openai",
                model="o4-mini",
                fallback=LLM(provider="openai", model="gpt-5"),
            ),
            executor=LLM(provider="openai", model="gpt-5-nano"),
            utils=LLMConfigUtils(
                outputter=LLM(provider="openai", model="gpt-5-nano"),
                hopper=LLM(provider="openai", model="gpt-4.1"),
            ),
        ),
        # from_file="/tmp/analyzer.jsonc"  # can be loaded from file
    )

    # 2. An action profile for handling easy & fast actions based on notifications
    action_profile = AgentProfile(
        name="note_taker",
        llm_config=LLMConfig(
            planner=LLM(provider="openai", model="o3"),
            orchestrator=LLM(provider="google", model="gemini-2.5-flash"),
            cortex=LLMWithFallback(
                provider="openai",
                model="o4-mini",
                fallback=LLM(provider="openai", model="gpt-5"),
            ),
            executor=LLM(provider="openai", model="gpt-4o-mini"),
            utils=LLMConfigUtils(
                outputter=LLM(provider="openai", model="gpt-5-nano"),
                hopper=LLM(provider="openai", model="gpt-4.1"),
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
        agent.init()

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
        agent.clean()
        print(f"\nTraces saved to: {traces_dir}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Next Steps

* Check the [api-reference.md](api-reference.md "mention") for detailed information
* See the [core-concepts.md](core-concepts.md "mention") to understand the SDK architecture
