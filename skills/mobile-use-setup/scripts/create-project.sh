#!/bin/bash
set -e

PROJECT_NAME="${1:-my-mobile-automation}"

echo "=== Creating Mobile-Use SDK Project ==="
echo "Project: $PROJECT_NAME"
echo ""

if ! command -v uv &> /dev/null; then
    echo "Error: UV not installed. Run:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "Creating project..."
uv init "$PROJECT_NAME"
cd "$PROJECT_NAME"

echo "Adding dependencies..."
uv add minitap-mobile-use python-dotenv

cat > .env.example << 'EOF'
# Configure the provider used by llm-config.override.jsonc.
OPEN_ROUTER_API_KEY=your_openrouter_key_here
# MINITAP_API_KEY=your_minitap_key_here
# OPENAI_API_KEY=your_openai_key_here
# ANTHROPIC_API_KEY=your_anthropic_key_here
# GOOGLE_API_KEY=your_google_key_here
EOF

cp .env.example .env

cat >> .gitignore << 'EOF'

# Environment variables
.env

# Local LLM config
llm-config.override.jsonc
EOF

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

echo "Downloading LLM config template..."
curl -sL https://raw.githubusercontent.com/minitap-ai/mobile-use/main/llm-config.override.template.jsonc \
    -o llm-config.override.jsonc || {
    echo "Warning: Could not download template. Creating placeholder."
    echo "// Copy from llm-config.override.template.jsonc and configure your models" > llm-config.override.jsonc
    echo "// Refer to llm-config.defaults.jsonc for recommended settings" >> llm-config.override.jsonc
}

echo ""
echo "=== Project Created ==="
echo ""
echo "Next steps:"
echo "  1. cd $PROJECT_NAME"
echo "  2. Edit .env with your API key(s)"
echo "  3. Configure llm-config.override.jsonc"
echo "  4. Update goal in main.py"
echo "  5. Connect your device"
echo "  6. Run: uv run main.py"
