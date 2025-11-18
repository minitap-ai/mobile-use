import asyncio

from pydantic import BaseModel, Field

from minitap.mobile_use.sdk import Agent


class MessageResult(BaseModel):
    """Structured result from messaging task."""

    messages_sent: int = Field(..., description="Number of messages successfully sent")
    contacts: list[str] = Field(..., description="List of contacts messaged")
    success: bool = Field(..., description="Whether all messages were sent successfully")


async def main() -> None:
    # Create agent with default configuration
    agent = Agent()

    try:
        await agent.init()

        # Use app lock to keep execution in WhatsApp
        # This ensures the agent stays in the app and relaunches if needed
        task = (
            agent.new_task("Send 'Happy New Year!' message to Alice, Bob, and Charlie on WhatsApp")
            .with_name("send_new_year_messages")
            .with_locked_app_package("com.whatsapp")  # Lock to WhatsApp
            .with_output_format(MessageResult)
            .with_max_steps(600)  # Messaging tasks may need more steps
            .build()
        )

        print("Sending messages with app lock enabled...")
        print("The agent will stay in WhatsApp and relaunch if needed.\n")

        result = await agent.run_task(request=task)

        if result:
            print("\n=== Messaging Complete ===")
            print(f"Messages sent: {result.messages_sent}")
            print(f"Contacts: {', '.join(result.contacts)}")
            print(f"Success: {result.success}")
        else:
            print("Failed to send messages")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await agent.clean()


if __name__ == "__main__":
    asyncio.run(main())
