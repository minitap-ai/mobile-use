"""
Simple Photo Organizer - Basic SDK Usage Example

This example demonstrates a straightforward way to use the mobile-use SDK
without builders or advanced configuration. It performs a real-world automation task:
1. Opens the photo gallery
2. Finds photos from a specific date
3. Creates an album and moves those photos into it

Run:
- python src/mobile_use/sdk/examples/simple_photo_organizer.py
"""

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
        await agent.init()

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
        await agent.clean()


if __name__ == "__main__":
    asyncio.run(main())
