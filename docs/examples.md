# Examples and Tutorials

This page provides practical examples and tutorials for using the Mobile Use SDK.

## Basic Examples

### Simple Text Automation

The most basic way to use the SDK is with string input and output:

```python
import asyncio
from minitap.mobile_use.sdk import Agent

async def basic_automation():
    agent = Agent()
    try:
        agent.init()
        
        # Run a simple task and get string output
        result = await agent.run_task(
            goal="Open the settings app and tell me what's the current system version",
            name="check_system_version"
        )
        
        print(f"System version: {result}")
    finally:
        agent.clean()

if __name__ == "__main__":
    asyncio.run(basic_automation())
```

### Using Structured Output

Define Pydantic models to get structured, typed outputs:

```python
import asyncio
from pydantic import BaseModel, Field
from minitap.mobile_use.sdk import Agent

class SystemInfo(BaseModel):
    os_name: str = Field(..., description="Operating system name")
    os_version: str = Field(..., description="Operating system version")
    device_model: str = Field(..., description="Device model name")
    available_storage: str = Field(..., description="Available storage space")

async def structured_output_demo():
    agent = Agent()
    try:
        agent.init()
        
        # Get structured system information
        system_info = await agent.run_task(
            goal="Open Settings, navigate to About Phone or About Device, and extract the system information",
            output=SystemInfo,
            name="get_system_info"
        )
        
        if system_info:
            print(f"OS: {system_info.os_name} {system_info.os_version}")
            print(f"Model: {system_info.device_model}")
            print(f"Storage: {system_info.available_storage}")
    finally:
        agent.clean()

if __name__ == "__main__":
    asyncio.run(structured_output_demo())
```

## Intermediate Tutorials

### Using Different Agent Profiles

Create specialized agent profiles for different task types:

```python
import asyncio
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import AgentProfile
from minitap.mobile_use.config import LLMConfig

async def profile_demo():
    # Create two specialized agent profiles
    thorough_profile = AgentProfile(
        name="thorough_inspector",
        llm_config=LLMConfig(
            model="gpt-4",
            temperature=0.2,
            system_prompt=(
                "You are a meticulous mobile UI inspector. "
                "Take your time to thoroughly analyze each screen element. "
                "Be precise and detailed in your observations."
            )
        )
    )
    
    quick_profile = AgentProfile(
        name="quick_navigator",
        llm_config=LLMConfig(
            model="gpt-3.5-turbo",
            temperature=0.7,
            system_prompt=(
                "You are a quick mobile navigator. "
                "Focus on completing tasks efficiently with minimal steps. "
                "Don't overthink - just get the job done fast."
            )
        )
    )
    
    # Create agent with both profiles
    agent = Agent(
        AgentConfigBuilder()
        .with_profile(thorough_profile)
        .with_profile(quick_profile)
        .build()
    )
    
    try:
        agent.init()
        
        # Use quick profile for navigation
        await agent.run_task(
            goal="Open the photo gallery app",
            profile="quick_navigator",
            name="open_gallery"
        )
        
        # Use thorough profile for analysis
        photo_details = await agent.run_task(
            goal="Analyze the first photo and describe it in detail",
            profile="thorough_inspector",
            name="analyze_photo"
        )
        
        print(f"Photo analysis: {photo_details}")
    finally:
        agent.clean()

if __name__ == "__main__":
    asyncio.run(profile_demo())
```

### Recording Execution Traces

Enable trace recording for debugging and visualization:

```python
import asyncio
from minitap.mobile_use.sdk import Agent

async def trace_recording_demo():
    agent = Agent()
    try:
        agent.init()
        
        # Create a task request with trace recording enabled
        task_request = agent.new_task(
            goal="Open the weather app and check the 5-day forecast"
        ).with_name("weather_forecast").with_trace_recording(enabled=True)
        
        result = await agent.run_task(request=task_request.build())
        print(f"Weather forecast: {result}")
        print("Trace saved to mobile-use-traces directory")
        
    finally:
        agent.clean()

if __name__ == "__main__":
    asyncio.run(trace_recording_demo())
```

## Advanced Tutorials

### Creating a Custom Task Pipeline

Build a multi-step automation pipeline that processes results between steps:

```python
import asyncio
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import AgentConfigBuilder

# Define structured models for each step
class MessagePriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class Message(BaseModel):
    sender: str = Field(..., description="Name or number of the message sender")
    text: str = Field(..., description="Content of the message")
    timestamp: str = Field(..., description="When the message was received")
    is_unread: bool = Field(..., description="Whether message is unread")
    
class MessagesResult(BaseModel):
    messages: List[Message] = Field(..., description="List of messages found")
    app_name: str = Field(..., description="Name of the messaging app used")

class ReplyResult(BaseModel):
    recipient: str = Field(..., description="Person replied to")
    message_sent: str = Field(..., description="Content of the sent reply")
    success: bool = Field(..., description="Whether reply was sent successfully")

async def message_workflow_demo():
    agent = Agent()
    
    try:
        agent.init()
        
        # Step 1: Check for new messages
        messages_result = await agent.run_task(
            goal="Open the main messaging app and identify the three most recent unread messages",
            output=MessagesResult,
            name="check_messages"
        )
        
        # Process results and determine action
        if messages_result and messages_result.messages:
            important_contacts = ["Boss", "Mom", "Dad", "Spouse", "Partner"]
            urgent_message = None
            
            for message in messages_result.messages:
                if message.is_unread and any(contact in message.sender for contact in important_contacts):
                    urgent_message = message
                    break
            
            # Step 2: Reply to important message if found
            if urgent_message:
                reply_result = await agent.run_task(
                    goal=f"Reply to {urgent_message.sender} with: 'Thanks for your message. I'll get back to you soon.'",
                    output=ReplyResult,
                    name="send_reply"
                )
                
                if reply_result and reply_result.success:
                    print(f"Successfully replied to {reply_result.recipient}")
                else:
                    print("Failed to send reply")
            else:
                print("No urgent messages found")
        else:
            print("No messages found or error occurred")
            
    finally:
        agent.clean()

if __name__ == "__main__":
    asyncio.run(message_workflow_demo())
```

### Custom Device Configuration

Connect to specific devices with custom server configurations:

```python
import asyncio
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import AgentConfigBuilder
from minitap.mobile_use.sdk.types import DevicePlatform, ApiBaseUrl

async def custom_device_demo():
    # Create a custom agent configuration
    config = AgentConfigBuilder() \
        .for_device(
            device_id="emulator-5554",  # ADB device ID
            platform=DevicePlatform.ANDROID
        ) \
        .with_server_config(
            adb_host="127.0.0.1",
            adb_port=5037,
            screen_api_base_url="http://localhost:9998",
            hw_bridge_base_url="http://localhost:9999"
        ) \
        .build()
    
    # Create agent with custom configuration
    agent = Agent(config)
    
    try:
        agent.init()
        
        # Run a task on the specific device
        result = await agent.run_task(
            goal="Open Settings and enable airplane mode, then disable it after 5 seconds",
            name="toggle_airplane_mode"
        )
        
        print(f"Task result: {result}")
    finally:
        agent.clean()

if __name__ == "__main__":
    asyncio.run(custom_device_demo())
```

## Real-World Use Cases

### Social Media Content Automation

```python
import asyncio
from datetime import datetime
from pydantic import BaseModel, Field
from minitap.mobile_use.sdk import Agent

class SocialPost(BaseModel):
    platform: str = Field(..., description="Social media platform where post was made")
    post_url: Optional[str] = Field(None, description="URL or identifier of the post")
    content: str = Field(..., description="Content that was posted")
    media_added: bool = Field(..., description="Whether media was attached to the post")
    timestamp: str = Field(..., description="When the post was published")

async def social_media_automation():
    agent = Agent()
    
    try:
        agent.init()
        
        # Prepare post content
        today = datetime.now().strftime("%Y-%m-%d")
        post_text = f"Excited to share my progress with Mobile Use SDK automation! #MobileAI #Python #{today}"
        
        # Post to social media
        result = await agent.run_task(
            goal=f"Open Instagram, create a new post with the text: '{post_text}'. "
                 f"Add the most recent photo from gallery, apply a filter, and publish it.",
            output=SocialPost,
            name="instagram_post"
        )
        
        if result:
            print(f"Posted to {result.platform} at {result.timestamp}")
            print(f"Content: {result.content}")
            print(f"Media included: {'Yes' if result.media_added else 'No'}")
    finally:
        agent.clean()

if __name__ == "__main__":
    asyncio.run(social_media_automation())
```

### E-commerce Product Research

```python
import asyncio
from typing import List
from pydantic import BaseModel, Field
from minitap.mobile_use.sdk import Agent

class Product(BaseModel):
    name: str = Field(..., description="Product name")
    price: str = Field(..., description="Product price")
    rating: Optional[float] = Field(None, description="Product rating (0-5 stars)")
    review_count: Optional[int] = Field(None, description="Number of reviews")

class ProductSearch(BaseModel):
    query: str = Field(..., description="Search query used")
    products: List[Product] = Field(..., description="Products found in search results")
    app_name: str = Field(..., description="E-commerce app used for search")

async def product_research():
    agent = Agent()
    
    try:
        agent.init()
        
        # Search for products
        search_result = await agent.run_task(
            goal="Open Amazon app, search for 'wireless headphones under $100', "
                 "and collect details on the top 5 search results",
            output=ProductSearch,
            name="amazon_search"
        )
        
        if search_result:
            print(f"Found {len(search_result.products)} products on {search_result.app_name}")
            
            # Sort by rating
            sorted_products = sorted(
                search_result.products, 
                key=lambda p: p.rating if p.rating is not None else 0, 
                reverse=True
            )
            
            # Display top products
            print("\nTop Products:")
            for i, product in enumerate(sorted_products[:3], 1):
                print(f"{i}. {product.name}")
                print(f"   Price: {product.price}")
                print(f"   Rating: {product.rating}/5 ({product.review_count} reviews)")
                print()
    finally:
        agent.clean()

if __name__ == "__main__":
    asyncio.run(product_research())
```

## Next Steps

- Learn about [Advanced Usage Patterns](advanced-usage.md) for more customization
- Check the [API Reference](api-reference.md) for detailed information
- See the [Troubleshooting Guide](troubleshooting.md) for common issues
