import os
from pathlib import Path

from pydantic import ValidationError

from minitap.mobile_use.config import LLMConfig, deep_merge_llm_config, get_default_llm_config
from minitap.mobile_use.utils.file import load_jsonc
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def load_llm_config_override(path: Path) -> LLMConfig:
    default_config = get_default_llm_config()

    override_config_dict = {}
    if os.path.exists(path):
        logger.info(f"Loading custom LLM config from {path.resolve()}...")
        with open(path) as f:
            override_config_dict = load_jsonc(f)
    else:
        logger.warning("Custom LLM config not found - using the default config")

    try:
        return deep_merge_llm_config(default_config, override_config_dict)
    except ValidationError as e:
        logger.error(f"Invalid LLM config: {e}")
        logger.info("Falling back to default config")
        return default_config
