# Troubleshooting Guide

This guide helps you diagnose and resolve common issues when working with the Mobile Use SDK.

## Device Connection Issues

### No Device Found

**Symptoms:**
- Error: `DeviceNotFoundError: No device found. Exiting.`
- Agent initialization fails

**Solutions:**

1. **Verify device connection:**
   ```bash
   # For Android
   adb devices
   
   # For iOS
   idevice_id -l
   ```

2. **Enable USB debugging (Android):**
   - Settings → About Phone → Tap "Build Number" 7 times
   - Settings → Developer options → USB debugging

3. **Trust computer (iOS):**
   - Unlock your device
   - Tap "Trust" when prompted

4. **Reset ADB:**
   ```bash
   adb kill-server
   adb start-server
   ```

5. **Specify device manually:**
   ```python
   from minitap.mobile_use.sdk.builders import AgentConfigBuilder
   from minitap.mobile_use.sdk.types import DevicePlatform
   
   config = (AgentConfigBuilder()
             .for_device("device_id_here", DevicePlatform.ANDROID)
             .build())
   agent = Agent(config)
   ```

### USB Connection Unstable

**Symptoms:**
- Random disconnections during automation
- `adb: error: device 'xxx' not found`

**Solutions:**

1. **Use a high-quality USB cable**
2. **Connect directly to computer** (not through USB hub)
3. **Increase ADB connection timeout:**
   ```bash
   adb shell settings put global adb_timeout 0
   ```
4. **For wireless debugging, ensure stable Wi-Fi:**
   ```bash
   # Connect wirelessly
   adb tcpip 5555
   adb connect device_ip:5555
   ```

## Server-Related Issues

### Server Startup Failure

**Symptoms:**
- Error: `ServerStartupError: Mobile-use servers failed to start`
- `Port in use` errors

**Solutions:**

1. **Check for port conflicts:**
   ```bash
   # For Linux/macOS
   sudo lsof -i :9998
   sudo lsof -i :9999
   
   # For Windows
   netstat -ano | findstr :9998
   netstat -ano | findstr :9999
   ```

2. **Manually kill conflicting processes:**
   ```bash
   # For Linux/macOS
   kill -9 <PID>
   
   # For Windows
   taskkill /F /PID <PID>
   ```

3. **Configure alternative ports:**
   ```python
   from minitap.mobile_use.sdk.builders import AgentConfigBuilder
   from minitap.mobile_use.sdk.types import ApiBaseUrl
   
   config = (AgentConfigBuilder()
             .with_server_config(
                 screen_api_base_url="http://localhost:9996",
                 hw_bridge_base_url="http://localhost:9997"
             )
             .build())
   agent = Agent(config)
   ```

### Device Hardware Bridge Connection Issues

**Symptoms:**
- Error: `Device Hardware Bridge failed to connect`
- Status: `NO_DEVICE`, `FAILED`, or `PORT_IN_USE`

**Solutions:**

1. **Check device connection** (see "No Device Found" section)
2. **Restart the bridge explicitly:**
   ```python
   from minitap.mobile_use.servers.start_servers import (
       start_device_hardware_bridge,
       start_device_screen_api
   )
   from minitap.mobile_use.servers.stop_servers import stop_servers
   from minitap.mobile_use.context import DevicePlatform
   
   # Stop any existing servers
   stop_servers(device_screen_api=True, device_hardware_bridge=True)
   
   # Start servers with explicit device ID
   device_id = "your_device_id"
   platform = DevicePlatform.ANDROID  # or DevicePlatform.IOS
   
   bridge_instance = start_device_hardware_bridge(device_id=device_id, platform=platform)
   api_process = start_device_screen_api(use_process=True)
   ```

3. **Check environment variables:**
   ```bash
   # Set debugging variables
   export MOBILE_USE_LOG_LEVEL=DEBUG
   ```

## Task Execution Issues

### Agent Not Initialized

**Symptoms:**
- Error: `AgentNotInitializedError`

**Solution:**
- Always call `agent.init()` before running tasks:
  ```python
  agent = Agent()
  agent.init()
  # Now you can run tasks
  ```

### Task Times Out or Fails

**Symptoms:**
- Task gets stuck or fails to complete
- Timeout errors

**Solutions:**

1. **Simplify the task goal:**
   Break complex tasks into simpler steps.
   
   ```python
   # Instead of
   await agent.run_task(
       goal="Open settings, go to network settings, enable airplane mode, wait 5 seconds, then disable airplane mode"
   )
   
   # Use multiple simpler tasks
   await agent.run_task(goal="Open settings and go to network settings")
   await agent.run_task(goal="Enable airplane mode")
   time.sleep(5)
   await agent.run_task(goal="Disable airplane mode")
   ```

2. **Increase max_steps limit:**
   ```python
   task_request = agent.new_task("Complex goal...")
       .with_max_steps(30)  # Default is usually 20
       
   await agent.run_task(request=task_request.build())
   ```

3. **Handle temporary device state issues:**
   ```python
   # Reset to home screen when stuck
   await agent.run_task(goal="Go back to the home screen")
   ```

### Incorrect Task Results

**Symptoms:**
- Task returns unexpected or incomplete data
- Structured output fields are missing or have incorrect values

**Solutions:**

1. **Be more specific in your goal:**
   ```python
   # Instead of
   goal="Check the weather"
   
   # Be more specific
   goal="Open the Weather app, check the current temperature in Celsius for the current location, and the forecast for tomorrow"
   ```

2. **Use structured output with clear field descriptions:**
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

3. **Try a different agent profile:**
   ```python
   # Create a more meticulous profile
   detailed_profile = AgentProfile(
       name="detail_oriented",
       llm_config=LLMConfig(
           model="gpt-4",
           temperature=0.2,
           system_prompt="You are meticulous and thorough. Carefully analyze each screen."
       )
   )
   
   # Use this profile for tasks requiring precision
   result = await agent.run_task(
       goal="Extract detailed information...",
       profile=detailed_profile
   )
   ```

## Error Handling and Debugging

### Enabling Debug Logs

Set more detailed logging for troubleshooting:

```python
import logging
from minitap.mobile_use.utils.logger import get_logger

# Set log level to DEBUG
logger = get_logger(__name__)
logger.setLevel(logging.DEBUG)

# Or use environment variable
import os
os.environ["MOBILE_USE_LOG_LEVEL"] = "DEBUG"
```

### Trace Recording for Debugging

Enable trace recording to capture screenshots and steps for debugging:

```python
task_request = agent.new_task("Your task goal")
    .with_trace_recording(enabled=True)
    .with_name("debug_trace")

await agent.run_task(request=task_request.build())
# Traces will be saved to mobile-use-traces directory by default
```

### Error Context Handling

```python
try:
    await agent.run_task(goal="Your task goal")
except Exception as e:
    error_type = type(e).__name__
    
    if error_type == "DeviceNotFoundError":
        print("No device connected. Please connect a device and try again.")
    elif error_type == "ServerStartupError":
        print("Failed to start required servers. Check for port conflicts.")
    elif error_type == "AgentTaskRequestError":
        print(f"Invalid task configuration: {e}")
    else:
        print(f"Unexpected error: {e}")
        
    # Always clean up resources
    agent.clean()
```

## LLM and API Issues

### API Key Authentication

**Symptoms:**
- Error related to API key authentication
- `openai.error.AuthenticationError` or similar

**Solutions:**

1. **Check API key in .env file:**
   ```
   OPENAI_API_KEY=your_api_key_here
   ```

2. **Set environment variables programmatically:**
   ```python
   import os
   os.environ["OPENAI_API_KEY"] = "your_api_key_here"
   ```

3. **Configure LLM in agent profile:**
   ```python
   from minitap.mobile_use.config import LLMConfig
   from minitap.mobile_use.sdk.types import AgentProfile
   
   profile = AgentProfile(
       name="custom_profile",
       llm_config=LLMConfig(
           model="gpt-4",
           api_key="your_api_key_here"
       )
   )
   ```

### LLM Rate Limits

**Symptoms:**
- Rate limit errors from OpenAI or other LLM providers
- Tasks failing during busy periods

**Solutions:**

1. **Implement exponential backoff:**
   ```python
   import time
   import random
   
   def run_with_backoff(task_func, max_retries=5):
       for attempt in range(max_retries):
           try:
               return task_func()
           except Exception as e:
               if "rate limit" in str(e).lower() and attempt < max_retries - 1:
                   backoff_time = (2 ** attempt) + random.random()
                   print(f"Rate limited. Retrying in {backoff_time:.1f}s...")
                   time.sleep(backoff_time)
               else:
                   raise
   ```

2. **Use a local LLM or self-hosted API** to avoid rate limits

## System Environment Issues

### Python Version Compatibility

**Symptoms:**
- Import errors or syntax errors
- `SyntaxError` or `ModuleNotFoundError`

**Solution:**
- Ensure you're using Python 3.10+ as required:
  ```bash
  python --version
  # Should be 3.10.x or higher
  
  # If needed, create a compatible virtual environment
  python3.10 -m venv venv
  source venv/bin/activate
  ```

### Dependency Conflicts

**Symptoms:**
- Import errors for specific modules
- Version conflicts between packages

**Solutions:**

1. **Create a clean virtual environment:**
   ```bash
   python -m venv fresh_env
   source fresh_env/bin/activate
   pip install minitap-mobile-use
   ```

2. **Check for dependency conflicts:**
   ```bash
   pip check
   ```

3. **Install specific versions if needed:**
   ```bash
   pip install 'packagename==version'
   ```

## Contact Support

If you're still experiencing issues after trying these troubleshooting steps:

1. Check the [GitHub Issues](https://github.com/minitap-ai/mobile-use/issues) for similar problems and solutions
2. File a new issue with:
   - Detailed description of the problem
   - Steps to reproduce
   - Error messages and logs
   - Environment information (Python version, OS, device details)
   - Code sample demonstrating the issue

## Next Steps

- Return to [API Reference](api-reference.md) for detailed method information
- Check [Advanced Usage](advanced-usage.md) for more complex solutions
