from __future__ import annotations

from pydantic import BaseModel, ConfigDict, SecretStr


class BrowserStackClientConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    username: str
    access_key: SecretStr
    device_name: str
    platform_version: str
    app_url: str
    hub_url: str | None = None
    project_name: str | None = None
    build_name: str | None = None
    session_name: str | None = None

    @classmethod
    def with_overrides(
        cls,
        username: str | None = None,
        access_key: str | None = None,
        device_name: str | None = None,
        platform_version: str | None = None,
        app_url: str | None = None,
        hub_url: str | None = None,
        project_name: str | None = None,
        build_name: str | None = None,
        session_name: str | None = None,
        base: BrowserStackClientConfig | None = None,
    ) -> BrowserStackClientConfig:
        """Create a BrowserStackClientConfig with only specified fields overridden."""
        if base is None:
            raise ValueError("base config is required for BrowserStackClientConfig.with_overrides")
        overrides = {
            k: v
            for k, v in {
                "username": username,
                "access_key": access_key,
                "device_name": device_name,
                "platform_version": platform_version,
                "app_url": app_url,
                "hub_url": hub_url,
                "project_name": project_name,
                "build_name": build_name,
                "session_name": session_name,
            }.items()
            if v is not None
        }
        if not overrides:
            return base
        return base.model_copy(update=overrides)


class WdaClientConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    wda_url: str = "http://localhost:8100"
    timeout: float = 30.0
    auto_start_iproxy: bool = True
    auto_start_wda: bool = True
    wda_project_path: str | None = None
    wda_startup_timeout: float = 120.0

    @classmethod
    def with_overrides(
        cls,
        wda_url: str | None = None,
        timeout: float | None = None,
        auto_start_iproxy: bool | None = None,
        auto_start_wda: bool | None = None,
        wda_project_path: str | None = None,
        wda_startup_timeout: float | None = None,
    ) -> WdaClientConfig:
        """Create a WdaClientConfig with only specified fields overridden.

        Example:
            config = WdaClientConfig.with_overrides(
                wda_url="http://localhost:8101",
                auto_start_wda=False,
            )
        """
        base = cls()
        overrides = {
            k: v
            for k, v in {
                "wda_url": wda_url,
                "timeout": timeout,
                "auto_start_iproxy": auto_start_iproxy,
                "auto_start_wda": auto_start_wda,
                "wda_project_path": wda_project_path,
                "wda_startup_timeout": wda_startup_timeout,
            }.items()
            if v is not None
        }
        if not overrides:
            return base
        return base.model_copy(update=overrides)


class IdbClientConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    host: str | None = None
    port: int | None = None

    @classmethod
    def with_overrides(
        cls,
        host: str | None = None,
        port: int | None = None,
    ) -> IdbClientConfig:
        """Create an IdbClientConfig with only specified fields overridden."""
        base = cls()
        overrides = {k: v for k, v in {"host": host, "port": port}.items() if v is not None}
        if not overrides:
            return base
        return base.model_copy(update=overrides)


class IosClientConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    wda: WdaClientConfig = WdaClientConfig()
    idb: IdbClientConfig = IdbClientConfig()
    browserstack: BrowserStackClientConfig | None = None

    @classmethod
    def with_overrides(
        cls,
        wda: WdaClientConfig | None = None,
        idb: IdbClientConfig | None = None,
        browserstack: BrowserStackClientConfig | None = None,
    ) -> IosClientConfig:
        """Create an IosClientConfig with only specified fields overridden."""
        base = cls()
        overrides = {
            k: v
            for k, v in {"wda": wda, "idb": idb, "browserstack": browserstack}.items()
            if v is not None
        }
        if not overrides:
            return base
        return base.model_copy(update=overrides)
