---
name: mobile-use-setup
description: Set up a local-first Minitap mobile-use SDK project for iOS or Android, including local devices, BrowserStack, Minitap cloud devices, and supported LLM providers.
---

# Mobile-Use SDK Setup

Set up mobile-use so the agent runs locally against a selected device.

## Gather Requirements

Ask only for information not already provided:

1. Target: iOS, Android, or both.
2. Device path: local physical device/emulator, BrowserStack, or a Minitap cloud device.
3. LLM provider: Minitap API, OpenAI, Anthropic, Google, OpenRouter, a local model, or another supported provider.

## Check Prerequisites

```bash
python3 --version  # Requires 3.12+
which uv

# Android local
which adb
adb devices

# iOS simulator
which idb_companion
xcrun simctl list devices

# iOS physical
which idevice_id
which appium
appium driver list
```

For missing dependencies, use the device-specific reference files in this skill.

## Create The Project

```bash
uv init <project-name>
cd <project-name>
uv add minitap-mobile-use python-dotenv
cp llm-config.override.template.jsonc llm-config.override.jsonc
```

Configure the selected provider in `llm-config.override.jsonc` and put only the required provider keys in `.env`. Add `.env` to `.gitignore`.

## Create The Starter

Generate task code that runs the agent locally:

```python
import asyncio

from dotenv import load_dotenv

from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import Builders
from minitap.mobile_use.sdk.types import AgentProfile

load_dotenv()


async def main() -> None:
    profile = AgentProfile(name="default", from_file="llm-config.override.jsonc")
    config = Builders.AgentConfig.with_default_profile(profile).build()
    agent = Agent(config=config)

    try:
        await agent.init()
        result = await agent.run_task(goal="Your automation goal", name="first-task")
        print(result)
    finally:
        await agent.clean()


if __name__ == "__main__":
    asyncio.run(main())
```

When selected, extend `config` with the BrowserStack or `for_cloud_device(...)` builder API.

## Verify

Verify the selected device is visible, then run:

```bash
uv run python -c "from minitap.mobile_use.sdk import Agent; print('SDK OK')"
uv run python main.py
```

Diagnose setup failures from actual command output. Do not silently switch device paths.
