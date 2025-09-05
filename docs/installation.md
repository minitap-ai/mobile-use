# Installation

## Prerequisites

Before installing the Mobile Use SDK, ensure you have the following:

* Python 3.12 or higher
* For Android automation:
  * Android SDK Platform Tools (adb)
  * A physical Android device or emulator
* For iOS automation:
  * A macOS environment
  * Xcode Command Line Tools
  * A physical iOS device or simulator
* [Maestro](https://maestro.mobile.dev/getting-started/installing-maestro) - framework used to interact with your device

## Environment Setup

### 1. Install the SDK

```bash
pip install minitap-mobile-use
```

Or install from source:

```bash
git clone https://github.com/minitap-ai/mobile-use.git
cd mobile-use
uv venv
source .venv/bin/activate # or for Windows: .venv\Scripts\activate
uv sync
```

### 2. Set Up Device Access

#### Android Setup

1. Enable Developer Options on your Android device
   * Go to Settings → About Phone
   * Tap "Build Number" 7 times to enable Developer Options
   * In Developer Options, enable "USB Debugging"
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

### 3. Default LLM Config

Create a `llm-config.defaults.jsonc` file which will contain the default specification of the LLM models that will be used:

```json
// Here is the default config that will be used if no override is provided.
{
  "planner": {
    "provider": "openai",
    "model": "gpt-5-nano"
  },
  "orchestrator": {
    "provider": "openai",
    "model": "gpt-5-nano"
  },
  "cortex": {
    "provider": "openai",
    "model": "gpt-5",
    "fallback": {
      "provider": "openai",
      "model": "gpt-5"
    }
  },
  "executor": {
    "provider": "openai",
    "model": "gpt-5-nano"
  },
  "utils": {
    "hopper": {
      // Needs at least a 256k context window.
      "provider": "openai",
      "model": "gpt-5-nano"
    },
    "outputter": {
      "provider": "openai",
      "model": "gpt-5-nano"
    }
  }
}

```

### 4. Configure Environment Variables

Create a `.env` file in your project root with necessary API keys based on the LLM models you want to use (i.e. only `OPENAI_API_KEY` is required if using the previous configuration):

```sh
# LLM API Keys
OPENAI_API_KEY=''
XAI_API_KEY=''
OPEN_ROUTER_API_KEY=''
GOOGLE_API_KEY=''
```

## Verifying Installation

Run a simple test to verify your installation:

<pre class="language-python"><code class="lang-python">from minitap.mobile_use.sdk import Agent
<strong>from minitap.mobile_use.sdk.types import AgentProfile
</strong>from minitap.mobile_use.sdk.builders import Builders

default_profile = AgentProfile(name="default", from_file="llm-config.defaults.jsonc")
agent_config = Builders.AgentConfig.with_default_profile(default_profile).build()
agent = Agent(config=agent_config)

initialized = agent.init()
print(f"Agent initialized: {initialized}")

agent.clean()
</code></pre>

If you see `Agent initialized: True`, your installation was successful!

## Next Steps

Now that you have the mobile-use SDK installed, move on to the [Quickstart Guide](quickstart.md) to run your first automation.
