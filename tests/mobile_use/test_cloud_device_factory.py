from minitap.mobile_use.clients.cloud_device_factory import CloudDeviceInstanceConfig
from minitap.mobile_use.config import Settings, settings


def test_minitap_api_base_url_default_is_canonical():
    assert (
        Settings.model_fields["MINITAP_API_BASE_URL"].default
        == "https://maas.app.minitap.ai/api/v1"
    )


def test_cloud_device_uses_shared_api_base_url(monkeypatch):
    monkeypatch.setattr(settings, "MINITAP_API_BASE_URL", "https://api.example.test/api/v1/")

    config = CloudDeviceInstanceConfig(api_key="test-key")

    assert config.base_url == "https://api.example.test/api/v1"


def test_cloud_device_preserves_explicit_base_url_behavior():
    config = CloudDeviceInstanceConfig(
        api_key="test-key",
        base_url="https://api.example.test/custom/",
    )

    assert config.base_url == "https://api.example.test/custom/api/v1"
