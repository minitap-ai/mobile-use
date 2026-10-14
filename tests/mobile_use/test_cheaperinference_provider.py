"""Tests for the Cheaper Inference LLM provider."""

from unittest.mock import patch

from pydantic import SecretStr


@patch("minitap.mobile_use.services.llm.ChatOpenAI")
@patch("minitap.mobile_use.services.llm.settings")
def test_get_cheaperinference_llm_uses_gateway(mock_settings, mock_chat_openai):
    from minitap.mobile_use.services.llm import get_cheaperinference_llm

    mock_settings.CHEAPER_INFERENCE_API_KEY = SecretStr("test-key")
    get_cheaperinference_llm(model_name="gpt-5.4-mini", temperature=0.5)
    kwargs = mock_chat_openai.call_args.kwargs
    assert kwargs["model"] == "gpt-5.4-mini"
    assert kwargs["temperature"] == 0.5
    assert kwargs["api_key"] == mock_settings.CHEAPER_INFERENCE_API_KEY
    assert kwargs["base_url"] == "https://api.cheaperinference.com/v1"
