# Core Concepts

## Architecture Overview

The Mobile Use SDK follows a layered architecture designed to provide both simplicity for common use cases and flexibility for advanced scenarios.

<p align="center">
  <img src="https://raw.githubusercontent.com/minitap-ai/mobile-use/main/doc/architecture.svg" alt="Mobile Use SDK Architecture" width="700">
</p>

## Key Components

### Agent

The `Agent` class is the primary entry point for the SDK. It coordinates all the components required for mobile automation:

- Initializes device connections
- Starts and manages required servers
- Creates and executes tasks
- Handles results and resource cleanup

```python
from minitap.mobile_use.sdk import Agent

# Create with default configuration
agent = Agent()  

# Or with custom configuration
from minitap.mobile_use.sdk.builders import AgentConfigBuilder
custom_config = AgentConfigBuilder().build()
agent = Agent(config=custom_config)
```

### Tasks and Task Requests

Tasks represent automation workflows to be executed on a mobile device:

- **Goal-based**: Tasks are defined using natural language goals
- **Traceable**: Execution can be recorded for debugging and visualization
- **Structured Output**: Results can be returned as typed Pydantic models

```python
# Simple task with string output
result = await agent.run_task(
    goal="Open settings and enable dark mode",
)

# Task with structured output
from pydantic import BaseModel
class ThemeSettings(BaseModel):
    dark_mode_enabled: bool
    theme_name: str

result = await agent.run_task(
    goal="Check the current theme settings",
    output=ThemeSettings,
)
```

### LangGraph Integration

The SDK uses [LangGraph](https://github.com/langchain-ai/langgraph) to orchestrate complex automation workflows:

- **Agent Thoughts**: The SDK captures agent reasoning for transparency and debugging
- **Step-by-step Execution**: Complex tasks are broken down into manageable steps
- **Dynamic Decision-making**: Agents adapt to what they see on screen

### Device Interaction

The SDK abstracts device interaction through two key components:

- **Screen API**: Captures screenshots and UI hierarchies for visual analysis
- **Hardware Bridge**: Sends touch events, key presses, and other hardware commands

## Agent Profiles

Agent profiles allow you to customize the behavior and capabilities of the automation agent:

```python
from minitap.mobile_use.sdk.types import AgentProfile
from minitap.mobile_use.config import LLMConfig

# Create a specialized agent profile
detail_oriented_profile = AgentProfile(
    name="detail_oriented",
    llm_config=LLMConfig(
        model="gpt-4",
        temperature=0.2,
    )
)

# Use it for a specific task
result = await agent.run_task(
    goal="Analyze all elements on the screen and describe their purpose",
    profile=detail_oriented_profile,
)
```

## Task Builder Pattern

For advanced use cases, the SDK provides a builder pattern for configuring tasks:

```python
task_request = agent.new_task("Open settings")
    .with_name("settings_task")
    .with_output_description("A summary of available settings")
    .with_trace_recording(enabled=True)

result = await agent.run_task(request=task_request.build())
```

## Next Steps

- Learn about [API Reference](api-reference.md) for detailed information on classes and methods
- See [Examples and Tutorials](examples.md) for practical use cases
- Explore [Advanced Usage](advanced-usage.md) for customization options
