# API Reference

This reference provides detailed documentation for the core classes and methods in the mobile-use SDK.

## Agent Class

The central class for mobile automation, responsible for managing device interaction and executing tasks.

```python
from minitap.mobile_use.sdk import Agent
```

### Constructor

```python
Agent(config: Optional[AgentConfig] = None)
```

* **config**: Optional. Custom agent configuration. If not provided, default configuration is used.

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

* **server\_restart\_attempts**: Maximum number of attempts to start servers if they fail
* **retry\_count**: Number of retries for API calls
* **retry\_wait\_seconds**: Seconds to wait between retries
* **Returns**: True if initialization succeeded

#### `run_task`

```python
async def run_task(
    self,
    *,
    goal: str | None = None,
    output: type[TOutput] | str | None = None,
    profile: str | AgentProfile | None = None,
    name: str | None = None,
    request: TaskRequest[TOutput] | None = None,
) -> str | dict | TOutput | None
```

Executes a mobile automation task.

* **goal**: Natural language description of what to accomplish
* **output**: Type of output (Pydantic model class or string description)
* **profile**: Agent profile to use (name or instance)
* **name**: Optional name for the task
* **request**: Pre-built TaskRequest (**alternative to individual parameters**)
* **Returns**: Task result (string, dict, or Pydantic model instance)

#### `new_task`

```python
def new_task(self, goal: str) -> TaskRequestBuilder[None]
```

Creates a new task request builder for configuring a task.

* **goal**: Natural language description of what to accomplish
* **Returns**: TaskRequestBuilder instance for fluent configuration

#### `clean`

```python
def clean(self, force: bool = False) -> None
```

Cleans up resources, stops servers, and resets the agent state.

* **force:** Can be set to **true** to clean zombie/pre-existing mobile-use servers

## TaskRequestBuilder\[TOutput=None] Class

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

#### `with_max_steps`

```python
def with_max_steps(self, max_steps: int) -> TaskRequestBuilder[TOutput]
```

Sets the maximum number of steps the task can take (equivalent to LangGraph recursion limit).

#### `with_llm_output_saving`

```python
def with_llm_output_saving(self, path: str) -> TaskRequestBuilder[TOutput]
```

Configures the path where the final mobile-use LLM output for the task must be saved (will be overwritten).

#### `with_thoughts_output_saving`

<pre class="language-python"><code class="lang-python"><strong>def with_thoughts_output_saving(self, path: str) -> TaskRequestBuilder[TOutput]
</strong></code></pre>

Configures the path where the LLM agent thoughts for the task must be saved (will be overwritten).

#### `with_output_description`

```python
def with_output_description(self, description: str) -> TaskRequestBuilder[TOutput]
```

Sets a natural language description of the expected output format.

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
def with_trace_recording(self, enabled: bool = True, path: str | Path | None = None) -> TaskRequestBuilder[TOutput]
```

Enables or disables trace recording for debugging.

#### `without_llm_output_saving`

```python
def without_llm_output_saving(self) -> TaskRequestBuilder[TOutput]
```

Disable LLM output saving for the task (in case it was previously enabled).

#### `without_thoughts_output_saving`

```python
def without_thoughts_output_saving(self) -> TaskRequestBuilder[TOutput]
```

Disable agent thoughts output saving for the task (in case it was previously enabled).

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
def for_device(self, platform: DevicePlatform, device_id: str) -> AgentConfigBuilder
```

Specifies a target device instead of auto-detection.

#### `add_profile`

```python
def add_profile(self, profile: AgentProfile) -> AgentConfigBuilder
```

Adds an agent profile.

#### `add_profiles`

```python
def add_profile(self, profiles: list[AgentProfile]) -> AgentConfigBuilder
```

Adds multiple agent profiles.

#### `with_default_profile`

```python
def with_default_profile(self, profile: str | AgentProfile) -> AgentConfigBuilder
```

Sets the default agent profile used for the tasks.

#### `with_hw_bridge`

```python
def with_hw_bridge(self, url: str | ApiBaseUrl) -> AgentConfigBuilder
```

Sets the base URL for Device Hardware Bridge API server.

#### `with_screen_api`

```python
def with_screen_api(self, url: str | ApiBaseUrl) -> AgentConfigBuilder
```

Sets the base URL for Device Screen API server.

#### `with_adb_server`

```python
def with_adb_server(self, host: str, port: int | None = None) -> AgentConfigBuilder
```

Sets the ADB server host and port.

#### `with_servers`

```python
def with_servers(self, servers: ServerConfig) -> AgentConfigBuilder
```

Configures server connections. It's basically a shortcut for:

* `with_hw_bridge(...)`
* `with_screen_api(...)`
* `with_adb_server(...)`

#### `with_default_task_config`

```python
def with_default_task_config(self, config: TaskRequestCommon) -> AgentConfigBuilder
```

Sets the default task configuration for tasks created by the agent.

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

* **goal**: str - Natural language description of the task goal
* **profile**: str | None - Name of the agent profile to use
* **task\_name**: str | None - Name of the task
* **output\_description**: str | None - Description of the expected output format
* **output\_format**: type\[TOutput] | None - Pydantic model class for typed output
* **max\_steps**: int - Maximum number of steps the agent can take
* **record\_trace**: bool - Whether to record execution traces
* **trace\_path**: Path - Directory to save trace data
* **llm\_output\_path**: Path | None - Path to save LLM outputs
* **thoughts\_output\_path**: Path | None - Path to save agent thoughts

## AgentProfile Class

Represents a profile for the mobile-use agent which is composed of multiple internal LLM agents.

```python
from minitap.mobile_use.sdk.types import AgentProfile
```

### Constructor

```python
AgentProfile(
    *,
    name: str,
    llm_config: LLMConfig | None = None,
    from_file: str | None = None,
)
```

* **name**: Name of the profile
* **llm\_config**: LLM configuration for the agent
* **from\_file**: Path to a file containing LLM configuration

N.B. `llm_config` and `from_file` are **mutually exclusive**.

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

* **MobileUseError**: Base exception for all SDK errors
* **AgentError**: Base exception for agent-related errors
* **AgentProfileNotFoundError**: Raised when a specified profile is not found
* **AgentTaskRequestError**: Raised for task request validation errors
* **AgentNotInitializedError**: Raised when agent methods are called before initialization
* **DeviceError**: Base exception for device-related errors
* **DeviceNotFoundError**: Raised when no device is found
* **ServerError**: Base exception for server-related errors
* **ServerStartupError**: Raised when server startup fails
