# API Reference

This reference provides detailed documentation for the core classes and methods in the Mobile Use SDK.

## Agent Class

The central class for mobile automation, responsible for managing device interaction and executing tasks.

```python
from minitap.mobile_use.sdk import Agent
```

### Constructor

```python
Agent(config: Optional[AgentConfig] = None)
```

- **config**: Optional. Custom agent configuration. If not provided, default configuration is used.

### Methods

#### `init`

```python
def init(
    self,
    server_restart_attempts: int = 3,
    retry_count: int = 5,
    retry_wait_seconds: int = 5,
) -> bool
```

Initializes the agent by connecting to a device and starting required servers.

- **server_restart_attempts**: Maximum number of attempts to start servers if they fail
- **retry_count**: Number of retries for API calls
- **retry_wait_seconds**: Seconds to wait between retries
- **Returns**: True if initialization succeeded

#### `run_task`

```python
async def run_task(
    self,
    *,
    goal: Optional[str] = None,
    output: Optional[type[TOutput] | str] = None,
    profile: Optional[str | AgentProfile] = None,
    name: Optional[str] = None,
    request: Optional[TaskRequest[TOutput]] = None,
) -> Optional[str | dict | TOutput]
```

Executes a mobile automation task.

- **goal**: Natural language description of what to accomplish
- **output**: Type of output (Pydantic model class or string description)
- **profile**: Agent profile to use (name or instance)
- **name**: Optional name for the task
- **request**: Pre-built TaskRequest (alternative to individual parameters)
- **Returns**: Task result (string, dict, or Pydantic model instance)

#### `new_task`

```python
def new_task(self, goal: str) -> TaskRequestBuilder[None]
```

Creates a new task request builder for configuring a task.

- **goal**: Natural language description of what to accomplish
- **Returns**: TaskRequestBuilder instance for fluent configuration

#### `clean`

```python
def clean(self) -> None
```

Cleans up resources, stops servers, and resets the agent state.

## TaskRequestBuilder Class

Fluent builder for configuring task requests.

```python
from minitap.mobile_use.sdk.builders import TaskRequestBuilder
```

### Methods

#### `with_name`

```python
def with_name(self, name: str) -> TaskRequestBuilder[TOutput]
```

Sets a name for the task.

#### `with_output_description`

```python
def with_output_description(self, description: str) -> TaskRequestBuilder[TOutput]
```

Sets a textual description of the expected output format.

#### `with_output_format`

```python
def with_output_format(self, output_format: type[TNewOutput]) -> TaskRequestBuilder[TNewOutput]
```

Sets a Pydantic model class as the output format.

#### `using_profile`

```python
def using_profile(self, profile: str | AgentProfile) -> TaskRequestBuilder[TOutput]
```

Sets the agent profile to use for this task.

#### `with_trace_recording`

```python
def with_trace_recording(self, enabled: bool = True, path: Optional[str | Path] = None) -> TaskRequestBuilder[TOutput]
```

Enables or disables trace recording for debugging.

#### `build`

```python
def build(self) -> TaskRequest[TOutput]
```

Builds the final TaskRequest object.

## AgentConfigBuilder Class

Fluent builder for configuring the agent.

```python
from minitap.mobile_use.sdk.builders import AgentConfigBuilder
```

### Methods

#### `for_device`

```python
def for_device(self, device_id: str, platform: DevicePlatform) -> AgentConfigBuilder
```

Specifies a target device instead of auto-detection.

#### `with_profile`

```python
def with_profile(self, profile: AgentProfile) -> AgentConfigBuilder
```

Adds an agent profile.

#### `with_default_profile`

```python
def with_default_profile(self, profile_name: str) -> AgentConfigBuilder
```

Sets the default agent profile.

#### `with_server_config`

```python
def with_server_config(
    self,
    *,
    adb_host: Optional[str] = None,
    adb_port: Optional[int] = None,
    screen_api_base_url: Optional[str | ApiBaseUrl] = None,
    hw_bridge_base_url: Optional[str | ApiBaseUrl] = None,
) -> AgentConfigBuilder
```

Configures server connections.

#### `build`

```python
def build(self) -> AgentConfig
```

Builds the final AgentConfig object.

## TaskRequest Class

Represents a mobile automation task request.

```python
from minitap.mobile_use.sdk.types import TaskRequest
```

### Attributes

- **goal**: str - Natural language description of the task goal
- **profile**: Optional[str] - Name of the agent profile to use
- **task_name**: Optional[str] - Name of the task
- **output_description**: Optional[str] - Description of the expected output format
- **output_format**: Optional[type[TOutput]] - Pydantic model class for typed output
- **max_steps**: int - Maximum number of steps the agent can take
- **record_trace**: bool - Whether to record execution traces
- **trace_path**: Path - Directory to save trace data
- **llm_output_path**: Optional[Path] - Path to save LLM outputs
- **thoughts_output_path**: Optional[Path] - Path to save agent thoughts

## AgentProfile Class

Represents a profile for an agent with specific capabilities.

```python
from minitap.mobile_use.sdk.types import AgentProfile
```

### Constructor

```python
AgentProfile(
    *,
    name: str,
    llm_config: Optional[LLMConfig] = None,
    from_file: Optional[str] = None,
)
```

- **name**: Name of the profile
- **llm_config**: LLM configuration for the agent
- **from_file**: Path to a file containing LLM configuration

## Error Classes

```python
from minitap.mobile_use.sdk.types.exceptions import (
    MobileUseError,
    AgentError,
    AgentProfileNotFoundError,
    AgentTaskRequestError,
    AgentNotInitializedError,
    DeviceError,
    DeviceNotFoundError,
    ServerError,
    ServerStartupError,
)
```

- **MobileUseError**: Base exception for all SDK errors
- **AgentError**: Base exception for agent-related errors
- **AgentProfileNotFoundError**: Raised when a specified profile is not found
- **AgentTaskRequestError**: Raised for task request validation errors
- **AgentNotInitializedError**: Raised when agent methods are called before initialization
- **DeviceError**: Base exception for device-related errors
- **DeviceNotFoundError**: Raised when no device is found
- **ServerError**: Base exception for server-related errors
- **ServerStartupError**: Raised when server startup fails
