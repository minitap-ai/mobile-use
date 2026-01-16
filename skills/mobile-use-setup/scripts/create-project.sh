#!/bin/bash
# Create a new mobile-use SDK project
# Usage: ./create-project.sh <project-name> [platform|local]

set -e

PROJECT_NAME="${1:-my-mobile-automation}"
MODE="${2:-platform}"

echo "=== Creating Mobile-Use SDK Project ==="
echo "Project: $PROJECT_NAME"
echo "Mode: $MODE"
echo ""

# Check UV
if ! command -v uv &> /dev/null; then
    echo "Error: UV not installed. Run:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Create project
echo "Creating project..."
uv init "$PROJECT_NAME"
cd "$PROJECT_NAME"

# Add dependencies
echo "Adding dependencies..."
uv add minitap-mobile-use python-dotenv

# Create .env.example
cat > .env.example << 'EOF'
# Minitap Platform API Key
# Get yours at: https://platform.minitap.ai/api-keys
MINITAP_API_KEY=your_api_key_here
EOF

# Create .env
cp .env.example .env

# Update .gitignore
cat >> .gitignore << 'EOF'

# Environment variables
.env

# Local LLM config
llm-config.override.jsonc
EOF

# Create main.py based on mode
if [ "$MODE" = "platform" ]; then
    cat > main.py << 'EOF'
"""
Mobile Automation with Minitap Platform

Usage:
    uv run main.py
"""

import asyncio
from dotenv import load_dotenv
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import PlatformTaskRequest

load_dotenv()


async def main() -> None:
    agent = Agent()
    await agent.init()  # Uses MINITAP_API_KEY from .env

    result = await agent.run_task(
        request=PlatformTaskRequest(
            task="your-task-name",  # Create this on platform.minitap.ai
        )
    )
    print(result)
    await agent.clean()


if __name__ == "__main__":
    asyncio.run(main())
EOF
else
    # Local mode
    cat > main.py << 'EOF'
"""
Mobile Automation with Local LLM Config

Usage:
    uv run main.py
"""

import asyncio
from dotenv import load_dotenv
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.types import AgentProfile
from minitap.mobile_use.sdk.builders import Builders

load_dotenv()


async def main() -> None:
    profile = AgentProfile(
        name="default",
        from_file="llm-config.override.jsonc"
    )
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
EOF

    # Create LLM config template
    cat > llm-config.override.jsonc << 'EOF'
{
  // LLM Configuration for Local Development
  // Add your API keys to .env: OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.

  "planner": {
    "provider": "openai",
    "model": "gpt-4o-mini"
  },
  "cortex": {
    "provider": "openai",
    "model": "gpt-4o"
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
EOF

    # Update .env.example for local mode
    cat >> .env.example << 'EOF'

# LLM Provider API Keys (for local mode)
OPENAI_API_KEY=your_openai_key_here
# ANTHROPIC_API_KEY=your_anthropic_key_here
# GOOGLE_API_KEY=your_google_key_here
EOF
fi

echo ""
echo "=== Project Created ==="
echo ""
echo "Next steps:"
echo "  1. cd $PROJECT_NAME"
echo "  2. Edit .env with your API key(s)"
if [ "$MODE" = "platform" ]; then
    echo "  3. Create a task on https://platform.minitap.ai"
    echo "  4. Update 'your-task-name' in main.py"
else
    echo "  3. Configure llm-config.override.jsonc"
    echo "  4. Update goal in main.py"
fi
echo "  5. Connect your device"
echo "  6. Run: uv run main.py"
