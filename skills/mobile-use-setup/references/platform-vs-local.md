# Platform vs Local Mode

Understanding the two approaches to LLM configuration in mobile-use SDK.

## Overview

| Aspect | Platform Mode | Local Mode |
|--------|---------------|------------|
| Setup complexity | Simple | More involved |
| LLM config | Managed by Minitap | You control |
| API keys needed | Just MINITAP_API_KEY | Provider keys (OpenAI, etc.) |
| Cost | Minitap pricing | Direct provider pricing |
| Customization | Via Platform UI | Full control |
| Offline capable | No | Yes (with local models) |

## Platform Mode (Recommended)

Minitap handles all LLM orchestration. You just need an API key.

### Pros
- Fastest setup (5 minutes)
- No LLM config files to manage
- Optimized model selection handled for you
- Task management UI
- Built-in observability and logging

### Cons
- Requires internet connection
- Dependent on Minitap service
- Less control over model selection

### Setup

1. Sign up at https://platform.minitap.ai
2. Create API key
3. Add to `.env`:
   ```
   MINITAP_API_KEY=sk-...
   ```
4. Create tasks via Platform UI

### Code

```python
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import PlatformTaskRequest

agent = Agent()
await agent.init()  # Uses MINITAP_API_KEY

result = await agent.run_task(
    request=PlatformTaskRequest(task="my-task")
)
```

## Local Mode

Full control over LLM configuration with your own API keys.

### Pros
- Complete control over models
- Use any supported provider
- Direct relationship with LLM providers
- Can use local models (Ollama, etc.)
- Works offline with local models

### Cons
- More complex setup
- Must manage config files
- Need to optimize model selection yourself
- Multiple API keys to manage

### Setup

1. Create `llm-config.override.jsonc`:
   ```jsonc
   {
     "planner": {
       "provider": "openai",
       "model": "gpt-4o-mini"
     },
     "cortex": {
       "provider": "openai",
       "model": "gpt-4o"  // Needs vision
     },
     "executor": {
       "provider": "openai",
       "model": "gpt-4o-mini"
     },
     "validator": {
       "provider": "openai",
       "model": "gpt-4o-mini"
     }
   }
   ```

2. Add provider keys to `.env`:
   ```
   OPENAI_API_KEY=sk-...
   ```

### Code

```python
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import AgentProfile
from minitap.mobile_use.sdk.builders import Builders

profile = AgentProfile(
    name="default",
    from_file="llm-config.override.jsonc"
)
config = Builders.AgentConfig.with_default_profile(profile).build()

agent = Agent(config=config)
await agent.init()

result = await agent.run_task(
    goal="Open calculator and compute 2+2",
    name="calc-test"
)
```

## Supported Providers (Local Mode)

| Provider | Config Value | Vision Support |
|----------|--------------|----------------|
| OpenAI | `openai` | gpt-4o, gpt-4-turbo |
| Anthropic | `anthropic` | claude-3-opus, claude-3-sonnet |
| Google | `google` | gemini-pro-vision |

## When to Use Each

**Use Platform Mode when:**
- Getting started / learning
- Want simplest setup
- Building production automations
- Need task management UI
- Want built-in observability

**Use Local Mode when:**
- Need specific model control
- Have existing provider relationships
- Running in air-gapped environment
- Want to use local models
- Cost optimization with specific providers

## Hybrid Approach

You can start with Platform mode and switch to Local later. The device setup and automation scripts remain the same - only the agent initialization changes.
