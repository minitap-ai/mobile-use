# mobile-use SDK Examples

Location: `src/mobile_use/sdk/examples/`

Run any example via:

- `python src/mobile_use/sdk/examples/<filename>.py`

## Practical Automation Examples

These examples demonstrate two different ways to use the SDK, each applying an appropriate level of complexity for the task at hand:

### platform_minimal_example.py - Painless integration with the Minitap platform

This script shows the simplest way to run minitap :

- Visit https://platform.minitap.ai to create a task and get your API key.
- Initialize the agent with your API key: .init(api_key=...).
- Ask the agent to run one of the tasks you’ve set up in the Minitap platform
  (e.g., "like-instagram-post").
- The task’s goal and settings live in the Minitap platform, you don’t need
  to hardcode them here.
- If you’ve created different profiles (LLM configurations) in the Minitap platform (like "fast-config"),
  you can pick which one to use with the `profile` field.

### simple_photo_organizer.py - Straightforward Approach

Demonstrates the simplest way to use the SDK for quick automation tasks:

- **Direct API calls** without builders or complex configuration
- Creates a photo album and organizes photos from a specific date
- Uses structured Pydantic output to capture results

### smart_notification_assistant.py - Feature-Rich Approach

Showcases more advanced SDK features while remaining practical:

- Uses builder pattern for configuring the agent and overriding the default task configurations
- Implements **multiple specialized agent profiles** for different reasoning tasks:
  - Analyzer profile for detailed inspection of notifications
  - Note taker profile for writing a summary of the notifications
- Enables **tracing** for debugging and visualization
- Includes **structured Pydantic models** with enums and nested relationships
- Demonstrates proper **exception handling** for different error types
- Shows how to set up task defaults for consistent configuration

## Usage Notes

- **Choosing an Approach**:

  - Use the direct approach (like `platform_minimal_example.py`) for painless setup using the Minitap platform. You can configure any task, save, run, and monitor them with a few clicks.
  - Use the simple approach (like `simple_photo_organizer.py`) for straightforward tasks, you configure settings yourself and every LLM call happens on your device.
  - Use the builder approach (like `smart_notification_assistant.py`) when you need more customization.

- **Device Detection**: The agent detects the first available device unless you specify one with `AgentConfigBuilder.for_device(...)`.

- **Servers**: With default base URLs (`localhost:9998/9999`), the agent starts the servers automatically. When you override URLs, it assumes servers are already running.

- **LLM API Keys**: Provide necessary keys (e.g., `OPENAI_API_KEY`) in a `.env` file at repo root; see `mobile_use/config.py`.

- **Traces**: When enabled, traces are saved to a specified directory (defaulting to `./mobile-use-traces/`) and can be useful for debugging and visualization.

- **Structured Output**: Pydantic models enable type safety when processing task outputs, making it easier to handle and chain results between tasks.

## Locked App Execution

You can restrict task execution to a specific app using the `with_locked_app_package()` method. This ensures the agent stays within the target application throughout the task execution.

```python
# Lock execution to WhatsApp
result = await agent.run_task(
    request=agent.new_task("Send message to Bob")
        .with_locked_app_package("com.whatsapp")
        .build()
)
```

**When locked to an app:**

- The system verifies the app is open before starting
- If the app is accidentally closed or navigated away from, the Contextor agent will attempt to relaunch it
- The Planner and Cortex agents will prioritize in-app actions

