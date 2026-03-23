"""Tests for the MiniMax LLM provider."""

import os
from unittest.mock import patch

import pytest
from pydantic import SecretStr


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(-0.5, 0.0), (0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (1.5, 1.0)],
)
@patch("minitap.mobile_use.services.llm.ChatOpenAI")
@patch("minitap.mobile_use.services.llm.settings")
def test_get_minimax_llm_clamps_temperature(mock_settings, mock_chat_openai, requested, expected):
    """MiniMax rejects temperatures outside (0, 1]; the provider must clamp them."""
    from minitap.mobile_use.services.llm import get_minimax_llm

    mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
    get_minimax_llm(temperature=requested)
    assert mock_chat_openai.call_args.kwargs["temperature"] == expected


@pytest.mark.integration
@patch("minitap.mobile_use.services.llm.settings")
def test_minimax_m27_llm_invoke(mock_settings):
    from minitap.mobile_use.services.llm import get_minimax_llm

    key = os.environ.get("MINIMAX_API_KEY")
    if not key or key in {"...", "your-minimax-api-key"}:
        pytest.skip("MINIMAX_API_KEY not set, skipping integration test")

    mock_settings.MINIMAX_API_KEY = SecretStr(key)
    client = get_minimax_llm(model_name="MiniMax-M2.7", temperature=0.7)
    response = client.invoke("Say 'hello' and nothing else.")
    assert len(response.content) > 0
