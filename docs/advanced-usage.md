# Advanced Usage Patterns

This guide covers advanced usage patterns for the Mobile Use SDK, helping you build more sophisticated automation solutions.

## Custom Agent Configuration

### Advanced Configuration with Builder Pattern

The builder pattern allows for fluent configuration of your agent:

```python
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import AgentConfigBuilder
from minitap.mobile_use.sdk.types import AgentProfile, DevicePlatform
from minitap.mobile_use.config import LLMConfig

# Create specialized profiles
detail_profile = AgentProfile(
    name="detail_expert",
    llm_config=LLMConfig(
        model="gpt-4", 
        temperature=0.2,
        system_prompt="You are an expert at analyzing mobile interfaces with exceptional attention to detail."
    )
)

speed_profile = AgentProfile(
    name="speed_expert",
    llm_config=LLMConfig(
        model="gpt-3.5-turbo", 
        temperature=0.7,
        system_prompt="You are an expert at efficiently completing mobile tasks with minimal steps."
    )
)

# Build a customized agent configuration
config = (
    AgentConfigBuilder()
    .for_device("emulator-5554", DevicePlatform.ANDROID)
    .with_profile(detail_profile)
    .with_profile(speed_profile)
    .with_default_profile("detail_expert")
    .with_server_config(
        adb_host="localhost",
        adb_port=5037,
        screen_api_base_url="http://localhost:9998",
        hw_bridge_base_url="http://localhost:9999"
    )
    .build()
)

agent = Agent(config)
```

### Loading Profiles from Configuration Files

Create reusable profiles stored in configuration files:

```python
import asyncio
from pathlib import Path
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import AgentConfigBuilder
from minitap.mobile_use.sdk.types import AgentProfile

async def run_with_config_files():
    # Load profiles from config files
    profile1 = AgentProfile(
        name="accessibility_expert",
        from_file="configs/accessibility_llm_config.jsonc"
    )
    
    profile2 = AgentProfile(
        name="ui_testing_expert",
        from_file="configs/ui_testing_llm_config.jsonc"
    )
    
    # Build config with loaded profiles
    config = (
        AgentConfigBuilder()
        .with_profile(profile1)
        .with_profile(profile2)
        .with_default_profile("ui_testing_expert")
        .build()
    )
    
    agent = Agent(config)
    
    try:
        agent.init()
        # Run tasks with specialized profiles
    finally:
        agent.clean()
```

## Task Management Patterns

### Sequential Task Execution

Chain tasks together using results from previous tasks:

```python
import asyncio
from typing import List
from pydantic import BaseModel, Field
from minitap.mobile_use.sdk import Agent

class AppInfo(BaseModel):
    name: str = Field(..., description="App name")
    package_name: str = Field(..., description="Package identifier")
    version: str = Field(..., description="App version")

class AppList(BaseModel):
    apps: List[AppInfo] = Field(..., description="List of installed apps")

class StorageUsage(BaseModel):
    app_name: str = Field(..., description="App name")
    storage_size: str = Field(..., description="Storage used by app")
    cache_size: str = Field(..., description="Cache size")
    data_size: str = Field(..., description="App data size")

async def sequential_tasks():
    agent = Agent()
    
    try:
        agent.init()
        
        # First task: Get list of installed apps
        apps_result = await agent.run_task(
            goal="Open Settings, go to Apps or Application Manager, and list the first 5 apps sorted by size",
            output=AppList,
            name="list_apps"
        )
        
        if not apps_result or not apps_result.apps:
            print("Failed to get app list")
            return
        
        # Second task: Get detailed storage info for largest app
        largest_app = apps_result.apps[0]
        storage_info = await agent.run_task(
            goal=f"Open Settings, go to Apps, find '{largest_app.name}', and get detailed storage information",
            output=StorageUsage,
            name="app_storage_details"
        )
        
        if storage_info:
            print(f"App: {storage_info.app_name}")
            print(f"Total storage: {storage_info.storage_size}")
            print(f"Cache: {storage_info.cache_size}")
            print(f"Data: {storage_info.data_size}")
            
            # Third task: Clear cache if it's large
            if "MB" in storage_info.cache_size or "GB" in storage_info.cache_size:
                await agent.run_task(
                    goal=f"Open Settings, go to Apps, find '{largest_app.name}', and clear its cache",
                    name="clear_app_cache"
                )
                print(f"Cache cleared for {largest_app.name}")
        
    finally:
        agent.clean()
```

### Parallel Task Execution

Run multiple tasks concurrently for efficiency:

```python
import asyncio
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import AgentConfigBuilder

async def parallel_tasks():
    # Create two agents for different devices
    config1 = AgentConfigBuilder().for_device("emulator-5554", DevicePlatform.ANDROID).build()
    config2 = AgentConfigBuilder().for_device("emulator-5556", DevicePlatform.ANDROID).build()
    
    agent1 = Agent(config1)
    agent2 = Agent(config2)
    
    try:
        # Initialize both agents
        agent1.init()
        agent2.init()
        
        # Run tasks in parallel
        task1 = agent1.run_task(
            goal="Open the contacts app and create a new contact named 'John Smith'",
            name="create_contact_device1"
        )
        
        task2 = agent2.run_task(
            goal="Open the messaging app and check for new messages",
            name="check_messages_device2"
        )
        
        # Wait for both tasks to complete
        result1, result2 = await asyncio.gather(task1, task2)
        
        print(f"Device 1 result: {result1}")
        print(f"Device 2 result: {result2}")
        
    finally:
        # Clean up resources
        agent1.clean()
        agent2.clean()
```

## Custom Workflow Patterns

### Task Retry and Error Handling

Implement robust error handling with task retries:

```python
import asyncio
import time
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types.exceptions import DeviceError, ServerError

async def robust_task_execution(max_retries=3, retry_delay=5):
    agent = Agent()
    
    try:
        # Initialize with error handling
        try:
            agent.init()
        except (DeviceError, ServerError) as e:
            print(f"Initialization error: {e}")
            print("Trying alternative initialization...")
            
            # Alternative initialization strategy
            agent = Agent(AgentConfigBuilder().with_server_config(
                screen_api_base_url="http://localhost:9996",
                hw_bridge_base_url="http://localhost:9997"
            ).build())
            agent.init()
        
        # Task execution with retries
        for attempt in range(max_retries):
            try:
                result = await agent.run_task(
                    goal="Open Instagram and post a photo from the gallery",
                    name=f"instagram_post_attempt_{attempt+1}"
                )
                
                # Success
                print(f"Task completed: {result}")
                break
                
            except Exception as e:
                print(f"Attempt {attempt+1} failed: {e}")
                
                if attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    # Optionally reset device state before retry
                    await agent.run_task(
                        goal="Go back to the home screen",
                        name="reset_state"
                    )
                else:
                    print("All retry attempts failed")
                    
    finally:
        agent.clean()
```

### Composable Task Builder

Create reusable task components with a builder approach:

```python
import asyncio
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import TaskRequestBuilder
from pathlib import Path

class TaskFactory:
    """Factory for creating common task patterns"""
    
    def __init__(self, agent):
        self.agent = agent
        
    def create_navigation_task(self, destination_app):
        """Create a task to navigate to a specific app"""
        return (
            self.agent.new_task(f"Open the {destination_app} app")
            .with_name(f"navigate_to_{destination_app.lower()}")
        )
    
    def create_data_extraction_task(self, source_app, data_description, output_model):
        """Create a task to extract data from an app"""
        return (
            self.agent.new_task(f"Open {source_app}, find {data_description}, and extract the information")
            .with_name(f"extract_{source_app.lower()}_data")
            .with_output_format(output_model)
        )
    
    def create_recording_task(self, goal, trace_dir=None):
        """Create a task with tracing enabled"""
        trace_path = trace_dir or Path("./traces")
        return (
            self.agent.new_task(goal)
            .with_trace_recording(enabled=True, path=trace_path)
            .with_name(f"recorded_task_{int(time.time())}")
        )

async def factory_demo():
    agent = Agent()
    
    try:
        agent.init()
        factory = TaskFactory(agent)
        
        # Create and run navigation task
        navigation_task = factory.create_navigation_task("Settings")
        await agent.run_task(request=navigation_task.build())
        
        # Create and run data extraction task
        from pydantic import BaseModel, Field
        
        class BatteryInfo(BaseModel):
            level: int = Field(..., description="Battery percentage")
            status: str = Field(..., description="Charging status")
            
        extraction_task = factory.create_data_extraction_task(
            "Settings", "battery information", BatteryInfo
        )
        battery_info = await agent.run_task(request=extraction_task.build())
        print(f"Battery at {battery_info.level}%, status: {battery_info.status}")
        
    finally:
        agent.clean()
```

## Integration Patterns

### Web API Integration

Combine Mobile Use SDK with web APIs for extended functionality:

```python
import asyncio
import requests
from datetime import datetime
from pydantic import BaseModel, Field
from minitap.mobile_use.sdk import Agent

class WeatherData(BaseModel):
    temperature: float = Field(..., description="Current temperature in Celsius")
    condition: str = Field(..., description="Weather condition (e.g., sunny, cloudy)")
    location: str = Field(..., description="Location name")

async def weather_automation():
    # Get weather data from API
    def get_weather_api_data(city):
        # Replace with actual weather API call
        api_key = "your_api_key"
        url = f"https://api.weatherapi.com/v1/current.json?key={api_key}&q={city}"
        
        try:
            response = requests.get(url)
            data = response.json()
            return {
                "temperature": data["current"]["temp_c"],
                "condition": data["current"]["condition"]["text"],
                "location": data["location"]["name"]
            }
        except Exception as e:
            print(f"API error: {e}")
            return None
    
    # Get weather from API
    weather_data = get_weather_api_data("San Francisco")
    if not weather_data:
        print("Failed to get weather data from API")
        return
    
    agent = Agent()
    try:
        agent.init()
        
        # Create weather note with API data
        await agent.run_task(
            goal=f"Open the notes app and create a new note titled 'Weather Update {datetime.now().strftime('%Y-%m-%d')}'. "
                 f"Add text: 'Current weather in {weather_data['location']}: {weather_data['temperature']}°C, "
                 f"{weather_data['condition']}'. Save the note.",
            name="create_weather_note"
        )
        
        print("Weather note created based on API data")
    finally:
        agent.clean()
```

### Scheduled Automation

Create scheduled tasks that run at specified intervals:

```python
import asyncio
import schedule
import time
from datetime import datetime
from minitap.mobile_use.sdk import Agent

class SocialMediaScheduler:
    def __init__(self):
        self.agent = Agent()
        self.initialized = False
        
    async def initialize(self):
        if not self.initialized:
            self.agent.init()
            self.initialized = True
        
    async def cleanup(self):
        if self.initialized:
            self.agent.clean()
            self.initialized = False
            
    async def post_daily_update(self):
        await self.initialize()
        
        date_str = datetime.now().strftime("%A, %B %d")
        post_text = f"Daily update for {date_str}. #automation #daily"
        
        try:
            result = await self.agent.run_task(
                goal=f"Open Twitter/X app, create a new post with text: '{post_text}', and publish it",
                name="daily_social_post"
            )
            print(f"Daily post result: {result}")
        except Exception as e:
            print(f"Failed to post daily update: {e}")
            
    async def check_social_notifications(self):
        await self.initialize()
        
        try:
            result = await self.agent.run_task(
                goal="Open Twitter/X, check for any new notifications, and tell me if there are any mentions or messages",
                name="check_notifications"
            )
            print(f"Notification check result: {result}")
        except Exception as e:
            print(f"Failed to check notifications: {e}")

# Set up scheduler
scheduler = SocialMediaScheduler()

async def run_scheduled_task(task_func):
    await task_func()

def schedule_runner():
    loop = asyncio.get_event_loop()
    while True:
        schedule.run_pending()
        time.sleep(1)

# Schedule tasks
schedule.every().day.at("09:00").do(
    lambda: asyncio.run(run_scheduled_task(scheduler.post_daily_update))
)
schedule.every(3).hours.do(
    lambda: asyncio.run(run_scheduled_task(scheduler.check_social_notifications))
)

# Clean up on exit
import atexit
atexit.register(lambda: asyncio.run(scheduler.cleanup()))

# Run the scheduler
schedule_runner()
```

## Performance Optimization

### Optimizing for Speed

Configure the SDK for faster execution:

```python
import asyncio
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import AgentConfigBuilder
from minitap.mobile_use.sdk.types import AgentProfile
from minitap.mobile_use.config import LLMConfig

async def optimized_for_speed():
    # Create a speed-optimized profile
    speed_profile = AgentProfile(
        name="speed_optimized",
        llm_config=LLMConfig(
            model="gpt-3.5-turbo",  # Faster model
            temperature=0.4,
            max_tokens=256,         # Limit token usage
            system_prompt=(
                "You are a high-speed mobile automation expert. "
                "Complete tasks efficiently with minimal steps. "
                "Don't overthink - focus on direct actions."
            )
        )
    )
    
    # Configure agent with optimization settings
    config = (
        AgentConfigBuilder()
        .with_profile(speed_profile)
        .with_default_profile("speed_optimized")
        .build()
    )
    
    agent = Agent(config)
    
    try:
        # Initialize with optimized retry settings
        agent.init(
            server_restart_attempts=1,  # Minimize restart attempts
            retry_count=2,              # Fewer retries
            retry_wait_seconds=1        # Shorter wait between retries
        )
        
        # Create task with limited steps
        task_request = agent.new_task("Open calculator, calculate 12345 * 67890, and return the result")
            .with_name("quick_calculation")
            # Limit maximum steps to improve speed
            .with_max_steps(10)
        
        start_time = time.time()
        result = await agent.run_task(request=task_request.build())
        elapsed_time = time.time() - start_time
        
        print(f"Task completed in {elapsed_time:.2f} seconds")
        print(f"Result: {result}")
        
    finally:
        agent.clean()
```

### Memory and Resource Management

Optimize resource usage for long-running processes:

```python
import asyncio
import gc
import psutil
import time
from minitap.mobile_use.sdk import Agent

async def resource_optimized_batch_processing(task_batch):
    process = psutil.Process()
    agent = None
    
    print(f"Initial memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")
    
    try:
        agent = Agent()
        agent.init()
        
        for i, task in enumerate(task_batch):
            print(f"Running task {i+1}/{len(task_batch)}")
            print(f"Memory before task: {process.memory_info().rss / 1024 / 1024:.2f} MB")
            
            # Run task
            result = await agent.run_task(goal=task, name=f"batch_task_{i}")
            print(f"Task result: {result}")
            
            # Force garbage collection between tasks
            gc.collect()
            print(f"Memory after GC: {process.memory_info().rss / 1024 / 1024:.2f} MB")
            
            # Brief pause between tasks to allow system resources to stabilize
            time.sleep(1)
            
    finally:
        # Clean up agent resources
        if agent:
            agent.clean()
            agent = None
            
        # Final garbage collection
        gc.collect()
        print(f"Final memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")
```

## Next Steps

- See the [Troubleshooting Guide](troubleshooting.md) for solving common issues
- Check the [API Reference](api-reference.md) for detailed method information
- Explore the [Examples](examples.md) for more practical use cases
