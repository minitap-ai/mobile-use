# AGENTS.md - mobile-use

Guidelines for AI coding agents working in this repository.

## Project Overview

- **Name**: minitap-mobile-use
- **Description**: AI-powered multi-agent system for Android/iOS device automation using LangGraph
- **Python**: 3.12+ required
- **Package Manager**: uv (https://github.com/astral-sh/uv)

## Tech Stack

- **AI Framework**: LangGraph, LangChain
- **CLI**: Typer
- **Data Validation**: Pydantic, pydantic-settings
- **Android**: adbutils, uiautomator2
- **iOS**: fb-idb, facebook-wda
- **Linting/Formatting**: Ruff
- **Type Checking**: Pyright

## Directory Structure

```
minitap/mobile_use/
├── agents/          # AI agents (planner, executor, orchestrator, cortex, contextor)
├── clients/         # Device clients (IDB, WDA, ADB, UIAutomator)
├── controllers/     # Device controllers (Android, iOS, unified)
├── graph/           # LangGraph state and graph definitions
├── sdk/             # SDK for programmatic use
├── services/        # LLM, accessibility, telemetry services
├── tools/           # Mobile automation tools (tap, swipe, type, etc.)
├── utils/           # Utility functions
├── config.py        # Configuration management
├── context.py       # Device and runtime context
└── main.py          # CLI entry point
```

## Commands

### Setup & Install
```bash
make setup           # Full setup (deps + pre-commit hooks)
make install         # Install dependencies only (uv sync --dev)
```

### Running
```bash
python ./minitap/mobile_use/main.py "Your automation goal"
# Or via installed CLI:
mobile-use "Your automation goal"
```

### Linting & Formatting
```bash
make lint            # Check formatting and linting (ruff)
make format          # Auto-format code (ruff format + ruff check --fix)
make typecheck       # Run type checking (pyright)
make precommit       # Run all pre-commit hooks
```

### Testing
```bash
make test            # Run all tests except iOS simulator
make test-ios        # Run iOS simulator tests
make test-all        # Run all tests including iOS

# Run a single test file
uv run pytest tests/mobile_use/test_file.py -v

# Run a single test function
uv run pytest tests/mobile_use/test_file.py::test_function_name -v

# Run tests matching a pattern
uv run pytest -k "pattern" -v

# Run tests by marker
uv run pytest -m ios_simulator -v
uv run pytest -m android -v
```

## Code Style

### Formatting (Ruff)
- **Line length**: 100 characters
- **Indent**: 4 spaces
- **Quote style**: Double quotes (`"`)
- **Target Python**: 3.12

### Imports
- **Absolute imports only** - relative imports are banned
- Order: standard library, third-party, local
- Use `from typing import` for type hints

```python
# Correct
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.config import LLMConfig

# Wrong - relative imports are banned
from .utils.logger import get_logger
from ..config import LLMConfig
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `DeviceContext`, `LLMConfig` |
| Functions/methods | snake_case | `get_logger`, `validate_providers` |
| Variables | snake_case | `device_id`, `llm_config` |
| Constants | UPPER_SNAKE_CASE | `ROOT_DIR`, `DEFAULT_LLM_CONFIG_FILENAME` |
| Private | `_prefix` | `_loggers`, `_deep_merge_dict` |
| Unused variables | `_` prefix | `_unused`, `_` |

### Type Annotations
- All functions must have type hints for parameters and return values
- Use `|` union syntax (Python 3.10+): `str | None` not `Optional[str]`
- Use `list`, `dict`, `tuple` lowercase (Python 3.9+)

### Pydantic Models
- Use `BaseModel` for data structures
- Use `BaseSettings` for configuration with environment variables
- Use `Field()` for descriptions and defaults
- Use `model_validator` for complex validation

## Error Handling

### Exception Hierarchy
Custom exceptions are defined in `minitap/mobile_use/sdk/types/exceptions.py`:

```
MobileUseError (base)
├── DeviceError
│   └── DeviceNotFoundError
├── ServerError
│   └── ServerStartupError
├── AgentError
│   ├── AgentNotInitializedError
│   └── AgentTaskRequestError
│       └── AgentProfileNotFoundError
├── PlatformServiceError
└── ExecutableNotFoundError
```

### Patterns
```python
raise ValueError("Task goal is required")           # Validation errors
raise RuntimeError(f"ffmpeg failed: {result}")      # Runtime errors
raise DeviceNotFoundError("No Android device")      # Domain-specific errors
```

## Logging

Use the custom logger from `minitap.mobile_use.utils.logger`:

```python
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

logger.debug("Debug message")
logger.info("Info message")
logger.success("Success message")
logger.warning("Warning message")
logger.error("Error message")
```

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new tap gesture support
fix: resolve screenshot capture on iOS 17
docs: update API documentation
refactor: simplify device controller logic
test: add tests for IDB client
```

## Test Markers

- `@pytest.mark.ios_simulator` - Tests requiring iOS simulator
- `@pytest.mark.android` - Tests requiring Android device or emulator
