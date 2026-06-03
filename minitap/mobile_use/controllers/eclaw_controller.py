"""EClaw controller — passthrough to the out-of-tree
``eclaw-mobile-use-driver`` package.

This module is a thin import shim so users can write
``from minitap.mobile_use.controllers.eclaw_controller import EclawController``
the same way they import :class:`AndroidDeviceController` and
:class:`iOSDeviceController`, while the actual implementation lives in a
separately versioned PyPI package maintained by the EClawbot team.

Install
-------
    pip install eclaw-mobile-use-driver

Usage
-----
    from minitap.mobile_use.controllers.eclaw_controller import EclawController

    controller = EclawController(
        device_id="<eclaw-device-uuid>",
        bot_secret="<32-hex botSecret>",
        entity_id=2,
    )

``EclawController`` implements the
:class:`MobileDeviceController` Protocol against the EClawbot HTTPS control
API (``/api/device/control`` + ``/api/device/screen-image``), which lets
the mobile-use LangGraph drive any phone where the user has installed the
EClaw app and toggled ``remote_control_enabled`` on. iOS coverage in v1 is
limited to the in-app WebView shim — native iOS apps are out of scope
until the EClaw side adopts ``idb-companion``.

References
----------
- Driver source / issue tracker:
  https://github.com/HankHuang0516/EClaw/tree/main/eclaw-mobile-use-driver
- Integration spec:
  https://github.com/HankHuang0516/EClaw/blob/main/docs/specs/mobile-use-integration.md
- Discussion / interest probe:
  https://github.com/minitap-ai/mobile-use/issues/199
"""

from __future__ import annotations

try:
    from eclaw_mobile_use_driver import EclawController  # type: ignore[import-not-found]
except ImportError as _exc:  # pragma: no cover — import-time guidance only.
    raise ImportError(
        "EclawController is provided by the external `eclaw-mobile-use-driver` "
        "package. Install it with:\n\n"
        "    pip install eclaw-mobile-use-driver\n\n"
        "See https://github.com/HankHuang0516/EClaw/tree/main/eclaw-mobile-use-driver "
        "for source, license (MIT), and the integration spec."
    ) from _exc


__all__ = ["EclawController"]
