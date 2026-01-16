# Agent Skills

Agent skills for AI coding assistants to help users set up and use the mobile-use SDK.

## Installation

```bash
npx add-skill minitap-ai/mobile-use
```

## Available Skills

### mobile-use-setup

Interactive setup wizard that guides users through:

- Choosing target platforms (iOS, Android, or both)
- Selecting LLM mode (Platform or Local)
- Installing dependencies
- Configuring devices (physical, simulator, or cloud)
- Creating their first automation project

**Triggers:** "set up mobile automation", "configure mobile-use SDK", "connect iOS device", "connect Android device"

## Skill Structure

```
skills/
└── mobile-use-setup/
    ├── SKILL.md              # Main skill instructions
    ├── scripts/
    │   ├── check-prerequisites.sh
    │   ├── create-project.sh
    │   └── verify-device.sh
    └── references/
        ├── ios-physical-device.md
        ├── android-device.md
        └── platform-vs-local.md
```

## Usage

Once installed, the skill activates automatically when you ask your AI coding agent:

```
"Help me set up mobile automation for my iOS app"
"I want to configure the mobile-use SDK"
"Connect my Android device for testing"
```

The agent will:
1. Ask clarifying questions about your setup preferences
2. Check and install prerequisites
3. Create a configured project
4. Guide you through device-specific setup
5. Verify everything works

## Contributing

To add a new skill:

1. Create a directory under `skills/`
2. Add `SKILL.md` with frontmatter (`name`, `description`) and instructions
3. Add helper scripts in `scripts/` (optional)
4. Add detailed docs in `references/` (optional)
5. Submit a PR
