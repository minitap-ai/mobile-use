# mobile-use SDK Examples

Location: `src/mobile_use/sdk/examples/`

Run any example via:

- `python src/mobile_use/sdk/examples/<filename>.py`

## Practical Automation Examples

These examples demonstrate local mobile-use patterns with different levels of customization.

### simple_photo_organizer.py - Straightforward Approach

Demonstrates the simplest supported approach for quick automation tasks:

- Direct goal-based task execution
- Creates a photo album and organizes photos from a specific date
- Uses structured Pydantic output to capture results

### smart_notification_assistant.py - Feature-Rich Approach

Shows the builder pattern, local profiles, tracing, structured models, and error handling.

## Usage Notes

- **Choosing an Approach**:

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
    request=agent.new_task("Send message to Bob").with_locked_app_package("com.whatsapp").build()
)
```

**When locked to an app:**

- The system verifies the app is open before starting
- If the app is accidentally closed or navigated away from, the Contextor agent will attempt to relaunch it
- The Planner and Cortex agents will prioritize in-app actions
