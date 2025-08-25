# Installation Guide

## Prerequisites

Before installing the Mobile Use SDK, ensure you have the following:

- Python 3.10 or higher
- For Android automation:
  - Android SDK Platform Tools (adb)
  - A physical Android device or emulator
- For iOS automation:
  - A macOS environment
  - Xcode Command Line Tools
  - A physical iOS device or simulator

## Environment Setup

### 1. Install the SDK

```bash
pip install minitap-mobile-use
```

Or install from source:

```bash
git clone https://github.com/minitap-ai/mobile-use.git
cd mobile-use
pip install -e .
```

### 2. Set Up Device Access

#### Android Setup

1. Enable Developer Options on your Android device
   - Go to Settings → About Phone
   - Tap "Build Number" 7 times to enable Developer Options
   - In Developer Options, enable "USB Debugging"

2. Connect your device and verify ADB connection:

```bash
adb devices
```

You should see your device listed.

#### iOS Setup

1. Connect your iOS device to your Mac
2. Trust the computer on your iOS device when prompted
3. Install required dependencies:

```bash
brew install libimobiledevice
```

### 3. Configure Environment Variables

Create a `.env` file in your project root with necessary API keys:

```
# LLM API Keys
OPENAI_API_KEY=your_openai_api_key

# Optional settings
MOBILE_USE_LOG_LEVEL=INFO
```

## Verifying Installation

Run a simple test to verify your installation:

```python
from minitap.mobile_use.sdk import Agent

agent = Agent()
initialized = agent.init()
print(f"Agent initialized: {initialized}")
agent.clean()
```

If you see "Agent initialized: True", your installation was successful!

## Next Steps

Now that you have the Mobile Use SDK installed, move on to the [Quickstart Guide](quickstart.md) to run your first automation.
