---
name: mobile-use-setup
description: Interactive setup wizard for Minitap mobile-use SDK. USE WHEN user wants to set up mobile automation, configure mobile-use SDK, connect iOS or Android devices, or create a new mobile testing project.
---

# Mobile-Use SDK Setup Wizard

Interactive guide for setting up the Minitap mobile-use SDK with support for iOS and Android devices, Platform and Local modes.

## When to Apply

This skill activates when users want to:
- Set up mobile automation for an app
- Configure the Minitap mobile-use SDK
- Connect physical iOS or Android devices
- Set up cloud virtual devices
- Create a new mobile testing project

## Setup Flow

### Phase 1: Gather Requirements

**Ask the user these questions using the AskUserQuestion tool:**

1. **Target Platform**
   - Question: "Which platform(s) do you want to automate?"
   - Options: iOS only, Android only, Both iOS and Android

2. **LLM Configuration Mode**
   - Question: "How do you want to configure AI/LLM?"
   - Options:
     - Platform (Recommended) - Minitap handles LLM config, just need API key
     - Local - Full control with local config files and your own API keys

3. **Device Type** (if iOS selected)
   - Question: "What iOS device setup do you need?"
   - Options:
     - Physical device (iPhone/iPad via USB)
     - Simulator (Xcode iOS Simulator)

4. **Device Type** (if Android selected)
   - Question: "What Android device setup do you need?"
   - Options:
     - Physical device (via USB/WiFi ADB)
     - Cloud device (Minitap virtual Android)

### Phase 2: Check Prerequisites

Run these checks based on user selections:

```bash
# Always check
python3 --version    # Requires 3.12+
which uv            # Package manager

# For iOS physical device
which idevice_id    # libimobiledevice
which appium        # Appium
appium driver list  # XCUITest driver

# For iOS simulator
which idb_companion  # Facebook idb

# For Android
which adb           # Android platform tools
adb devices         # Device connection
```

### Phase 3: Install Missing Dependencies

**iOS Physical Device Setup:**
```bash
# Install libimobiledevice
brew install libimobiledevice

# Install Appium + XCUITest
npm install -g appium
appium driver install xcuitest
```

**iOS Simulator Setup:**
```bash
brew tap facebook/fb
brew install idb-companion
```

**Android Setup:**
```bash
# macOS
brew install --cask android-platform-tools

# Linux
sudo apt install android-tools-adb
```

**UV Package Manager:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Phase 4: Create Project

```bash
# Create new project
uv init <project-name>
cd <project-name>

# Add SDK
uv add minitap-mobile-use python-dotenv
```

### Phase 5: Configure Credentials

**For Platform Mode:**
1. Direct user to https://platform.minitap.ai to create account
2. Navigate to API Keys → Create API Key
3. Create .env file:
```
MINITAP_API_KEY=<their-key>
```
4. Add .env to .gitignore

**For Local Mode:**
1. Copy the config template:
   ```bash
   cp llm-config.override.template.jsonc llm-config.override.jsonc
   ```
2. Edit `llm-config.override.jsonc` with preferred models (refer to `llm-config.defaults.jsonc` for recommended settings)
3. Add provider API keys to .env (OPENAI_API_KEY, etc.) or set MINITAP_API_KEY for optimized config

### Phase 6: Device-Specific Setup

**iOS Physical Device (requires manual Xcode steps):**

Inform user they need to:
1. Open WebDriverAgent in Xcode:
   ```bash
   open ~/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj
   ```
2. Sign these targets with their Apple ID:
   - WebDriverAgentRunner
   - WebDriverAgentLib
   - IntegrationApp
3. Change Bundle IDs to unique values
4. Build IntegrationApp once with device connected
5. Trust developer certificate on device: Settings → General → VPN & Device Management

**Android Physical Device:**

Inform user they need to:
1. Enable Developer Options (tap Build Number 7 times)
2. Enable USB Debugging
3. Connect device and tap "Allow" on USB debugging prompt

### Phase 7: Create Starter Script

Generate main.py based on configuration:

**Platform Mode:**
```python
import asyncio
from dotenv import load_dotenv
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import PlatformTaskRequest

load_dotenv()

async def main() -> None:
    agent = Agent()
    await agent.init()

    result = await agent.run_task(
        request=PlatformTaskRequest(task="your-task-name")
    )
    print(result)
    await agent.clean()

if __name__ == "__main__":
    asyncio.run(main())
```

**Local Mode:**
```python
import asyncio
from dotenv import load_dotenv
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import AgentProfile
from minitap.mobile_use.sdk.builders import Builders

load_dotenv()

async def main() -> None:
    profile = AgentProfile(name="default", from_file="llm-config.override.jsonc")
    config = Builders.AgentConfig.with_default_profile(profile).build()

    agent = Agent(config=config)
    await agent.init()

    result = await agent.run_task(
        goal="Your automation goal here",
        name="task-name"
    )
    print(result)
    await agent.clean()

if __name__ == "__main__":
    asyncio.run(main())
```

### Phase 8: Verify Setup

Run verification based on device type:

```bash
# iOS physical
idevice_id -l

# iOS simulator
xcrun simctl list devices

# Android
adb devices

# Test SDK import
uv run python -c "from minitap.mobile_use.sdk import Agent; print('SDK OK')"
```

## Quick Reference

| Setup Type | Key Dependencies | Verification |
|------------|------------------|--------------|
| iOS Physical | Appium, XCUITest, libimobiledevice | `idevice_id -l` |
| iOS Simulator | idb-companion | `xcrun simctl list` |
| Android Physical | ADB | `adb devices` |
| Android Cloud | None (Platform only) | N/A |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Python < 3.12 | Install Python 3.12+ via pyenv or homebrew |
| UV not found | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| idevice_id not found | `brew install libimobiledevice` |
| ADB not found | `brew install --cask android-platform-tools` |
| WDA build fails | Check Xcode signing for all 3 targets |
| Device unauthorized | Enable USB debugging, tap Allow on device |
| CLT version error | `sudo xcode-select --install` |

## Examples

**Example 1: New iOS automation project**
```
User: "Help me set up mobile automation for my iOS app"
→ Ask: Platform preference (iOS), Mode (Platform), Device (Physical)
→ Check: python3, uv, libimobiledevice, appium
→ Install: Missing dependencies
→ Create: Project with uv init
→ Configure: .env with MINITAP_API_KEY
→ Guide: Xcode WebDriverAgent signing
→ Verify: idevice_id -l shows device
```

**Example 2: Android cloud setup**
```
User: "Set up mobile testing with cloud devices"
→ Ask: Platform (Android), Mode (Platform), Device (Cloud)
→ Check: python3, uv
→ Create: Project with uv init
→ Configure: .env with MINITAP_API_KEY
→ Guide: Create Virtual Mobile on platform.minitap.ai
→ Generate: main.py with for_cloud_mobile config
```

**Example 3: Full local development setup**
```
User: "I want full control over LLM config for mobile automation"
→ Ask: Platform (Both), Mode (Local), Devices (Physical)
→ Check: All dependencies
→ Create: Project, llm-config.override.jsonc
→ Configure: Provider API keys in .env
→ Guide: Device-specific setup for iOS and Android
→ Generate: main.py with local profile config
```
