# Troubleshooting

This guide helps you diagnose and resolve common issues when working with the Mobile Use SDK.

## Device Connection Issues

### No Device Found

**Symptoms:**

* Error: `DeviceNotFoundError: No device found. Exiting.`
* Agent initialization fails

**Solutions:**

1.  **Verify device connection:**

    ```bash
    # For Android
    adb devices

    # For iOS
    idevice_id -l
    ```
2. **Enable USB debugging (Android):**
   * Settings → About Phone → Tap "Build Number" 7 times
   * Settings → Developer options → USB debugging
3. **Trust computer (iOS):**
   * Unlock your device
   * Tap "Trust" when prompted
4.  **Reset ADB:**

    ```bash
    adb kill-server
    adb start-server
    ```
5.  **Specify device manually:**

    <pre class="language-python"><code class="lang-python"><strong>from minitap.mobile_use.sdk.builders import Builders
    </strong>from minitap.mobile_use.sdk.types import DevicePlatform

    config = (Builders.AgentConfig
              .for_device(platform=DevicePlatform.ANDROID, device_id="device_id_here")
              .build())
    agent = Agent(config=config)
    </code></pre>

### USB Connection Unstable

**Symptoms:**

* Random disconnections during automation
* `adb: error: device 'xxx' not found`

**Solutions:**

1. **Use a high-quality USB cable**
2. **Connect directly to computer** (not through USB hub)
3.  **Increase ADB connection timeout:**

    ```bash
    adb shell settings put global adb_timeout 0
    ```
4.  **For wireless debugging, ensure stable Wi-Fi:**

    ```bash
    # Connect wirelessly
    adb tcpip 5555
    adb connect device_ip:5555
    ```

## Server-Related Issues

**Symptoms:** mobile-use servers fail to start

**Solution:** preemptively kill any zombie server before initializing the agent

```python
from minitap.mobile_use.sdk.builders import Builders
from minitap.mobile_use.sdk.types import DevicePlatform

agent = Agent()
# Clear any zombie mobile-use servers
agent.clean(force=True)
agent.init()
# ...
agent.clean()
```

## Task Execution Issues

### Agent Not Initialized

**Symptoms:**

* Error: `AgentNotInitializedError`

**Solution:**

*   Always call `agent.init()` before running tasks:

    ```python
    agent = Agent()
    agent.init()
    # Now you can run tasks
    ```

### Task Times Out or Fails

**Symptoms:**

* Task gets stuck or fails to complete
* Timeout errors

**Solutions:**

1.  **Simplify the task goal:** Break complex tasks into simpler steps.

    <pre class="language-python"><code class="lang-python"><strong># Notes: This example is intentionally simple for demonstration purposes.
    </strong><strong>
    </strong><strong># Instead of
    </strong>await agent.run_task(
        goal="Open settings, go to network settings, enable airplane mode, wait 5 seconds, then disable airplane mode"
    )

    # Use multiple simpler tasks
    await agent.run_task(goal="Open settings and go to network settings")
    await agent.run_task(goal="Enable airplane mode")
    time.sleep(5)
    await agent.run_task(goal="Disable airplane mode")
    </code></pre>
2.  **Increase max\_steps limit:**

    ```python
    task_request = (
        agent.new_task("Complex goal...")
        .with_max_steps(500)  # Default is 400 which should be more than enough
    )
        
    await agent.run_task(request=task_request.build())
    ```

### Incorrect Task Results

**Symptoms:**

* Task returns unexpected or incomplete data
* Structured output fields are missing or have incorrect values

**Solutions:**

1.  **Be more specific in your goal:**

    ```python
    # Instead of
    goal="Check the weather"

    # Be more specific
    goal="Open the Weather app, check the current temperature in Celsius for the current location, and the forecast for tomorrow"
    ```
2.  **Use structured output with clear field descriptions:**

    ```python
    from pydantic import BaseModel, Field

    class WeatherInfo(BaseModel):
        current_temp: float = Field(..., description="Current temperature in Celsius")
        condition: str = Field(..., description="Current weather condition (e.g. sunny, cloudy)")
        tomorrow_forecast: str = Field(..., description="Weather forecast description for tomorrow")
        
    result = await agent.run_task(
        goal="Check weather for today and tomorrow",
        output=WeatherInfo
    )
    ```

## Error Handling and Debugging

### Trace Recording for Debugging

Enable trace recording to capture screenshots and steps for debugging:

```python
task_request = (
    agent.new_task("Your task goal")
    .with_trace_recording(enabled=True)
    .with_name("debug_trace")
)

await agent.run_task(request=task_request.build())
# Traces will be saved to `mobile-use-traces` directory by default
```

## LLM and API Issues

### API Key Authentication

**Symptoms:**

* Error related to API key authentication
* `openai.error.AuthenticationError` or similar

**Solutions:**

1.  **Ensure the API keys for all LLMs you use in your agent profiles are available as environment variables in your `.env` file:**

    ```
    OPENAI_API_KEY=''
    XAI_API_KEY=''
    OPEN_ROUTER_API_KEY=''
    GOOGLE_API_KEY=''
    ```
2.  **Set environment variables programmatically if required:**

    ```python
    import os
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["XAI_API_KEY"] = ""
    os.environ["OPEN_ROUTER_API_KEY"] = ""
    os.environ["GOOGLE_API_KEY"] = ""
    ```

## System Environment Issues

### Python Version Compatibility

**Symptoms:**

* Import errors or syntax errors
* `SyntaxError` or `ModuleNotFoundError`

**Solution:**

*   Ensure you're using Python 3.12+ as required:

    ```bash
    python --version
    # Should be 3.12.x or higher

    # If needed, create a compatible virtual environment
    python3.12 -m venv venv
    source venv/bin/activate
    ```
* We highly recommend you use [UV](https://docs.astral.sh/uv/guides/install-python/) for managing your project and packages. Refer to the [installation.md](installation.md "mention") page for a clean installation.

## Contact Support

If you're still experiencing issues after trying these troubleshooting steps:

1. Check the [GitHub Issues](https://github.com/minitap-ai/mobile-use/issues) for similar problems and solutions
2. File a new issue with:
   * Detailed description of the problem
   * Steps to reproduce
   * Error messages and logs
   * Environment information (Python version, OS, device details)
   * Code sample demonstrating the issue

## Next Steps

* Return to [API Reference](api-reference.md) for detailed method information
* Check [examples.md](examples.md "mention") to see how this SDK can be used
