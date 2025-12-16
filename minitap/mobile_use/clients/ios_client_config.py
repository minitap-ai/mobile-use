from __future__ import annotations

from dataclasses import replace

from pydantic import BaseModel, ConfigDict


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
        return replace(base, **overrides)


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
        return replace(base, **overrides)


class IosClientConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    wda: WdaClientConfig = WdaClientConfig()
    idb: IdbClientConfig = IdbClientConfig()

    @classmethod
    def with_overrides(
        cls,
        wda: WdaClientConfig | None = None,
        idb: IdbClientConfig | None = None,
    ) -> IosClientConfig:
        """Create an IosClientConfig with only specified fields overridden."""
        base = cls()
        overrides = {k: v for k, v in {"wda": wda, "idb": idb}.items() if v is not None}
        if not overrides:
            return base
        return replace(base, **overrides)
