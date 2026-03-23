"""Unit and integration tests for MiniMax LLM provider."""

from unittest.mock import MagicMock, patch

import pytest

from minitap.mobile_use.config import LLM, LLMConfig, LLMConfigUtils, LLMWithFallback


class TestMiniMaxProviderConfig:
    """Unit tests for MiniMax provider configuration."""

    def test_llm_provider_accepts_minimax(self):
        """MiniMax should be a valid LLMProvider literal."""
        llm = LLM(provider="minimax", model="MiniMax-M2.7")
        assert llm.provider == "minimax"
        assert llm.model == "MiniMax-M2.7"

    def test_llm_provider_accepts_minimax_highspeed(self):
        """MiniMax-M2.7-highspeed should be a valid model."""
        llm = LLM(provider="minimax", model="MiniMax-M2.7-highspeed")
        assert llm.provider == "minimax"
        assert llm.model == "MiniMax-M2.7-highspeed"

    def test_llm_with_fallback_minimax(self):
        """MiniMax should work as both primary and fallback provider."""
        llm = LLMWithFallback(
            provider="minimax",
            model="MiniMax-M2.7",
            fallback=LLM(provider="minimax", model="MiniMax-M2.7-highspeed"),
        )
        assert llm.provider == "minimax"
        assert llm.fallback.provider == "minimax"
        assert llm.fallback.model == "MiniMax-M2.7-highspeed"

    def test_minimax_provider_str(self):
        """LLM __str__ should include minimax provider."""
        llm = LLM(provider="minimax", model="MiniMax-M2.7")
        assert "minimax" in str(llm)
        assert "MiniMax-M2.7" in str(llm)

    def test_minimax_as_fallback_for_openai(self):
        """MiniMax can serve as a fallback for another provider."""
        llm = LLMWithFallback(
            provider="openai",
            model="gpt-5-nano",
            fallback=LLM(provider="minimax", model="MiniMax-M2.7"),
        )
        assert llm.provider == "openai"
        assert llm.fallback.provider == "minimax"

    @patch("minitap.mobile_use.config.settings")
    def test_validate_provider_minimax_with_key(self, mock_settings):
        """validate_provider should pass when MINIMAX_API_KEY is set."""
        mock_settings.MINIMAX_API_KEY = "test-key"
        llm = LLM(provider="minimax", model="MiniMax-M2.7")
        # Should not raise
        llm.validate_provider("test_agent")

    @patch("minitap.mobile_use.config.settings")
    def test_validate_provider_minimax_without_key(self, mock_settings):
        """validate_provider should raise when MINIMAX_API_KEY is missing."""
        mock_settings.MINIMAX_API_KEY = None
        llm = LLM(provider="minimax", model="MiniMax-M2.7")
        with pytest.raises(Exception, match="MINIMAX_API_KEY"):
            llm.validate_provider("test_agent")

    def test_full_config_with_minimax_m27(self):
        """A full LLMConfig using MiniMax M2.7 should validate correctly."""
        minimax_llm = LLMWithFallback(
            provider="minimax",
            model="MiniMax-M2.7",
            fallback=LLM(provider="minimax", model="MiniMax-M2.7-highspeed"),
        )
        config = LLMConfig(
            planner=minimax_llm,
            orchestrator=minimax_llm,
            contextor=minimax_llm,
            cortex=minimax_llm,
            executor=minimax_llm,
            utils=LLMConfigUtils(
                outputter=minimax_llm,
                hopper=minimax_llm,
            ),
        )
        assert config.planner.provider == "minimax"
        assert config.planner.model == "MiniMax-M2.7"
        assert config.get_agent("planner").fallback.model == "MiniMax-M2.7-highspeed"

    def test_invalid_provider_rejected(self):
        """An invalid provider should be rejected by Pydantic validation."""
        with pytest.raises(Exception):
            LLM(provider="nonexistent_provider", model="test")

    def test_deep_merge_preserves_minimax_override(self):
        """deep_merge_llm_config should apply MiniMax overrides correctly."""
        from minitap.mobile_use.config import deep_merge_llm_config, get_default_llm_config

        default = get_default_llm_config()
        override = {
            "planner": {
                "provider": "minimax",
                "model": "MiniMax-M2.7",
            }
        }
        merged = deep_merge_llm_config(default, override)
        assert merged.planner.provider == "minimax"
        assert merged.planner.model == "MiniMax-M2.7"
        # Other agents should remain unchanged
        assert merged.orchestrator.provider == "openai"

    def test_deep_merge_minimax_with_fallback(self):
        """deep_merge_llm_config should apply MiniMax fallback overrides."""
        from minitap.mobile_use.config import deep_merge_llm_config, get_default_llm_config

        default = get_default_llm_config()
        override = {
            "cortex": {
                "provider": "minimax",
                "model": "MiniMax-M2.7",
                "fallback": {
                    "provider": "minimax",
                    "model": "MiniMax-M2.7-highspeed",
                },
            }
        }
        merged = deep_merge_llm_config(default, override)
        assert merged.cortex.provider == "minimax"
        assert merged.cortex.model == "MiniMax-M2.7"
        assert merged.cortex.fallback.provider == "minimax"
        assert merged.cortex.fallback.model == "MiniMax-M2.7-highspeed"


class TestMiniMaxLLMService:
    """Unit tests for MiniMax LLM service functions."""

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_returns_chat_openai(self, mock_settings):
        """get_minimax_llm should return a ChatOpenAI instance."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        client = get_minimax_llm(model_name="MiniMax-M2.7", temperature=0.7)

        assert client.model_name == "MiniMax-M2.7"
        assert "minimax" in str(client.openai_api_base).lower()

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_default_model(self, mock_settings):
        """get_minimax_llm should use MiniMax-M2.7 as default model."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        client = get_minimax_llm()
        assert client.model_name == "MiniMax-M2.7"

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_highspeed_model(self, mock_settings):
        """get_minimax_llm should accept MiniMax-M2.7-highspeed model."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        client = get_minimax_llm(model_name="MiniMax-M2.7-highspeed")
        assert client.model_name == "MiniMax-M2.7-highspeed"

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_base_url(self, mock_settings):
        """get_minimax_llm should use the correct MiniMax API base URL."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        client = get_minimax_llm()
        assert "api.minimax.io" in str(client.openai_api_base)

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_no_api_key_raises(self, mock_settings):
        """get_minimax_llm should raise when MINIMAX_API_KEY is missing."""
        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = None
        with pytest.raises(AssertionError):
            get_minimax_llm()

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_custom_temperature(self, mock_settings):
        """get_minimax_llm should accept custom temperature."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        client = get_minimax_llm(temperature=0.5)
        assert client.temperature == 0.5

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_temperature_clamped_high(self, mock_settings):
        """Temperature above 1.0 should be clamped to 1.0."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        client = get_minimax_llm(temperature=1.5)
        assert client.temperature == 1.0

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_temperature_clamped_low(self, mock_settings):
        """Temperature below 0.0 should be clamped to 0.0."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        client = get_minimax_llm(temperature=-0.5)
        assert client.temperature == 0.0

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_temperature_zero(self, mock_settings):
        """Temperature of exactly 0.0 should be accepted."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        client = get_minimax_llm(temperature=0.0)
        assert client.temperature == 0.0

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_minimax_llm_temperature_one(self, mock_settings):
        """Temperature of exactly 1.0 should be accepted."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        client = get_minimax_llm(temperature=1.0)
        assert client.temperature == 1.0

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_llm_dispatches_to_minimax(self, mock_settings):
        """get_llm should dispatch to get_minimax_llm for minimax provider."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        mock_settings.OPENAI_API_KEY = None
        mock_settings.GOOGLE_API_KEY = None
        mock_settings.XAI_API_KEY = None
        mock_settings.OPEN_ROUTER_API_KEY = None
        mock_settings.MINITAP_API_KEY = None

        minimax_llm = LLMWithFallback(
            provider="minimax",
            model="MiniMax-M2.7",
            fallback=LLM(provider="minimax", model="MiniMax-M2.7-highspeed"),
        )
        config = LLMConfig(
            planner=minimax_llm,
            orchestrator=minimax_llm,
            contextor=minimax_llm,
            cortex=minimax_llm,
            executor=minimax_llm,
            utils=LLMConfigUtils(
                outputter=minimax_llm,
                hopper=minimax_llm,
            ),
        )

        ctx = MagicMock()
        ctx.llm_config = config
        ctx.execution_setup = None

        client = get_llm(ctx, "planner")
        assert client.model_name == "MiniMax-M2.7"
        assert "api.minimax.io" in str(client.openai_api_base)

    @patch("minitap.mobile_use.services.llm.settings")
    def test_get_llm_dispatches_fallback_to_minimax(self, mock_settings):
        """get_llm with use_fallback should dispatch fallback minimax model."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_llm

        mock_settings.MINIMAX_API_KEY = SecretStr("test-key")
        mock_settings.OPENAI_API_KEY = None
        mock_settings.GOOGLE_API_KEY = None
        mock_settings.XAI_API_KEY = None
        mock_settings.OPEN_ROUTER_API_KEY = None
        mock_settings.MINITAP_API_KEY = None

        minimax_llm = LLMWithFallback(
            provider="minimax",
            model="MiniMax-M2.7",
            fallback=LLM(provider="minimax", model="MiniMax-M2.7-highspeed"),
        )
        config = LLMConfig(
            planner=minimax_llm,
            orchestrator=minimax_llm,
            contextor=minimax_llm,
            cortex=minimax_llm,
            executor=minimax_llm,
            utils=LLMConfigUtils(
                outputter=minimax_llm,
                hopper=minimax_llm,
            ),
        )

        ctx = MagicMock()
        ctx.llm_config = config
        ctx.execution_setup = None

        client = get_llm(ctx, "planner", use_fallback=True)
        assert client.model_name == "MiniMax-M2.7-highspeed"
        assert "api.minimax.io" in str(client.openai_api_base)


class TestMiniMaxIntegration:
    """Integration tests for MiniMax provider (require MINIMAX_API_KEY)."""

    @pytest.fixture
    def minimax_api_key(self):
        """Get MiniMax API key from environment, skip if not available."""
        import os

        key = os.environ.get("MINIMAX_API_KEY")
        if not key:
            pytest.skip("MINIMAX_API_KEY not set, skipping integration test")
        return key

    @patch("minitap.mobile_use.services.llm.settings")
    def test_minimax_m27_client_creation(self, mock_settings, minimax_api_key):
        """Integration: Create a real MiniMax M2.7 client with valid config."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr(minimax_api_key)
        client = get_minimax_llm(model_name="MiniMax-M2.7", temperature=0.7)
        assert client is not None
        assert client.model_name == "MiniMax-M2.7"

    @patch("minitap.mobile_use.config.settings")
    def test_minimax_full_config_validation(self, mock_settings, minimax_api_key):
        """Integration: Full LLMConfig with MiniMax validates providers."""
        from pydantic import SecretStr

        mock_settings.MINIMAX_API_KEY = SecretStr(minimax_api_key)
        mock_settings.OPENAI_API_KEY = None
        mock_settings.GOOGLE_API_KEY = None
        mock_settings.XAI_API_KEY = None
        mock_settings.OPEN_ROUTER_API_KEY = None
        mock_settings.MINITAP_API_KEY = None

        minimax_llm = LLMWithFallback(
            provider="minimax",
            model="MiniMax-M2.7",
            fallback=LLM(provider="minimax", model="MiniMax-M2.7-highspeed"),
        )
        config = LLMConfig(
            planner=minimax_llm,
            orchestrator=minimax_llm,
            contextor=minimax_llm,
            cortex=minimax_llm,
            executor=minimax_llm,
            utils=LLMConfigUtils(
                outputter=minimax_llm,
                hopper=minimax_llm,
            ),
        )
        # Should not raise
        config.validate_providers()

    @patch("minitap.mobile_use.services.llm.settings")
    def test_minimax_m27_llm_invoke(self, mock_settings, minimax_api_key):
        """Integration: Invoke MiniMax M2.7 LLM with a simple prompt."""
        from pydantic import SecretStr

        from minitap.mobile_use.services.llm import get_minimax_llm

        mock_settings.MINIMAX_API_KEY = SecretStr(minimax_api_key)
        client = get_minimax_llm(model_name="MiniMax-M2.7", temperature=0.7)
        response = client.invoke("Say 'hello' and nothing else.")
        assert response is not None
        assert len(response.content) > 0
