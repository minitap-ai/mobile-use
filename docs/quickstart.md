# Quickstart

This guide will help you run your first mobile automation task using the mobile-use SDK.

## Creating Your First Automation

Let's write a simple script that opens a calculator app and performs a basic calculation:

```python
import asyncio
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import AgentProfile
from minitap.mobile_use.sdk.builders import Builders

async def main():
    # Create an agent (see Quickstart for the file `llm-config.defaults.jsonc`)
    default_profile = AgentProfile(name="default", from_file="llm-config.defaults.jsonc")
    agent_config = Builders.AgentConfig.with_default_profile(default_profile).build()
    agent = Agent(config=agent_config)
    
    try:
        # Initialize the agent (connect to the first available device)
        agent.init()
        
        # Define a simple task goal
        result = await agent.run_task(
            goal="Open the calculator app, calculate 123 * 456, and tell me the result",
            name="calculator_demo"
        )
        
        # Print the result
        print(f"Result: {result}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Always clean up when finished
        agent.clean()

if __name__ == "__main__":
    asyncio.run(main())
```

Save this file as `calculator_demo.py` and run it:

```bash
python calculator_demo.py
```

## Getting Structured Output

mobile-use SDK can return structured data using Pydantic models:

```python
import asyncio
from pydantic import BaseModel, Field
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import AgentProfile
from minitap.mobile_use.sdk.builders import Builders

# Define a model for structured output
class CalculationResult(BaseModel):
    expression: str = Field(..., description="The mathematical expression calculated")
    result: float = Field(..., description="The result of the calculation")
    app_used: str = Field(..., description="The name of the calculator app used")

async def main():
    # Create an agent (see Quickstart for the file `llm-config.defaults.jsonc`)
    default_profile = AgentProfile(name="default", from_file="llm-config.defaults.jsonc")
    agent_config = Builders.AgentConfig.with_default_profile(default_profile).build()
    agent = Agent(config=agent_config)
    
    try:
        agent.init()
        
        # Request structured output using Pydantic model
        result = await agent.run_task(
            goal="Open the calculator app, calculate 123 * 456, and tell me the result",
            output=CalculationResult,
            name="structured_calculator"
        )
        
        if result:
            print(f"Expression: {result.expression}")
            print(f"Result: {result.result}")
            print(f"App used: {result.app_used}")
        
    finally:
        agent.clean()

if __name__ == "__main__":
    asyncio.run(main())
```

## Next Steps

You've now created your first mobile automation! To learn more:

1. Explore [Core Concepts](core-concepts.md) to understand the architecture
2. See more [Examples and Tutorials](examples.md)
3. Read the [API Reference](api-reference.md) for detailed information about available classes and methods
