import sys

import inquirer
from rich.console import Console
from rich.prompt import Prompt


def select_provider_and_model(
    console: Console,
    available_providers: list[str],
    available_models: dict,
    default_provider: str,
    default_model: str,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str]:
    """
    Interactive selection of LLM provider and model with arrow-key dropdowns when available.

    Args:
        console: Rich console for output
        available_providers: List of available provider names
        available_models: Dict mapping providers to their available models
        default_provider: Default provider to use
        default_model: Default model to use
        provider: Pre-selected provider (optional)
        model: Pre-selected model (optional)

    Returns:
        Tuple of (selected_provider, selected_model)
    """
    final_provider = provider
    final_model = model

    # Interactive provider selection
    if not final_provider:
        console.print("\n🤖 [bold cyan]LLM Provider Selection[/bold cyan]")
        final_provider = _select_from_list(
            console=console,
            item_type="provider",
            choices=available_providers,
            default=default_provider,
            message="Select LLM provider",
        )

    # Interactive model selection
    if not final_model:
        console.print(f"\n🎯 [bold green]Model Selection for {final_provider}[/bold green]")
        available_model_list = (
            available_models[final_provider]
            if final_provider
            else available_models[default_provider]
        )

        default_model_for_provider = (
            default_model if default_model in available_model_list else available_model_list[0]
        )

        final_model = _select_from_list(
            console=console,
            item_type="model",
            choices=available_model_list,
            default=default_model_for_provider,
            message=f"Select model for {final_provider}",
        )

    return final_provider, final_model


def _select_from_list(
    console: Console,
    item_type: str,
    choices: list[str],
    default: str,
    message: str,
) -> str:
    """
    Select an item from a list using arrow keys when available, fallback to numbered selection.

    Args:
        console: Rich console for output
        item_type: Type of item being selected (for error messages)
        choices: List of choices to select from
        default: Default choice
        message: Message to display in dropdown

    Returns:
        Selected choice
    """
    # Try arrow-key dropdown if TTY is available, fallback to numbered selection
    if sys.stdin.isatty():
        try:
            questions = [
                inquirer.List(
                    "selection",
                    message=f"{message} (use arrow keys)",
                    choices=choices,
                    default=default,
                ),
            ]
            answers = inquirer.prompt(questions)
            return answers["selection"] if answers else default
        except Exception:
            # Fallback to numbered selection
            return _numbered_selection(console, item_type, choices, default)
    else:
        return _numbered_selection(console, item_type, choices, default)


def _numbered_selection(console: Console, item_type: str, choices: list[str], default: str) -> str:
    """Fallback numbered selection when arrow keys aren't available."""
    choices_text = "\n".join([f"  {i + 1}. {choice}" for i, choice in enumerate(choices)])
    console.print(f"Available {item_type}s:\n{choices_text}")

    default_idx = choices.index(default) + 1 if default in choices else 1

    while True:
        choice = Prompt.ask(
            f"Select {item_type} (1-{len(choices)}) or press Enter for default",
            default=str(default_idx),
        )
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(choices):
                return choices[choice_idx]
            else:
                console.print("[red]Invalid choice. Please try again.[/red]")
        except ValueError:
            console.print("[red]Please enter a number.[/red]")


def display_llm_config(console: Console, provider: str, model: str) -> None:
    """Display the selected LLM configuration with colors."""
    from rich.text import Text

    config_text = Text()
    config_text.append("🤖 LLM Configuration: ", style="bold white")
    config_text.append("Provider: ", style="white")
    config_text.append(f"{provider}", style="bold cyan")
    config_text.append(" | Model: ", style="white")
    config_text.append(f"{model}", style="bold green")

    console.print(config_text)
