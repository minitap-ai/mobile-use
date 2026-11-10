"""Fix round 1: app launch on devices without hardware keys, and launchable-package lookup."""

import asyncio
from unittest.mock import MagicMock

from minitap.mobile_use.controllers import platform_specific_commands_controller as psc
from minitap.mobile_use.controllers.android_controller import (
    AndroidDeviceController,
    resolve_launcher_component,
)


class FakeDevice:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def shell(self, cmd):
        cmd = " ".join(cmd) if isinstance(cmd, list) else cmd
        self.calls.append(cmd)
        for prefix, out in self.responses:
            if cmd.startswith(prefix):
                return out
        return ""


def controller(dev):
    c = AndroidDeviceController("s", MagicMock(), MagicMock(), 720, 1600)
    c._device = dev
    return c


def test_launch_uses_resolved_launcher_activity():
    dev = FakeDevice(
        [
            ("cmd package resolve-activity", "priority=0 preferredOrder=0\ncom.app.x/.Main\n"),
            ("am start -n com.app.x/.Main", "Starting: Intent { cmp=com.app.x/.Main }"),
        ]
    )
    assert asyncio.run(controller(dev).launch_app("com.app.x")) is True
    assert not any(c.startswith("monkey") for c in dev.calls)


def test_launch_falls_back_to_monkey_without_system_keys():
    dev = FakeDevice(
        [
            ("cmd package resolve-activity", "No activity found"),
            ("monkey --pct-syskeys 0 -p com.app.x", "Events injected: 1\n__exit=0"),
        ]
    )
    assert asyncio.run(controller(dev).launch_app("com.app.x")) is True
    assert any("--pct-syskeys 0" in c for c in dev.calls)


def test_launch_failure_is_reported_not_ignored():
    # bare monkey used to exit 251 ("SYS_KEYS has no physical keys") and still return True
    dev = FakeDevice(
        [
            ("cmd package resolve-activity", ""),
            ("monkey", "** No activities found to run, monkey aborted.\n__exit=252"),
        ]
    )
    assert asyncio.run(controller(dev).launch_app("com.app.x")) is False


def test_resolve_component_ignores_other_packages():
    dev = FakeDevice([("cmd package resolve-activity", "other.pkg/.A\n")])
    assert resolve_launcher_component(dev, "com.app.x") is None


def test_list_packages_keeps_only_launchable_packages(monkeypatch):
    dev = FakeDevice(
        [
            (
                "pm list packages -f",
                "package:/a.apk=com.app.settings\npackage:/b.apk=com.app.providers.settings\n"
                "package:/c.apk=com.app.settings.intelligence\npackage:/d.apk=com.app.notes\n",
            ),
            (
                "cmd package query-activities",
                "2 activities found:\n  Activity #0:\n    priority=0\n"
                "    com.app.settings/.Settings\n  Activity #1:\n    com.app.notes/.Main\n",
            ),
        ]
    )
    monkeypatch.setattr(psc, "get_adb_device", lambda ctx: dev)
    ctx = MagicMock()
    ctx.device.mobile_platform = psc.DevicePlatform.ANDROID
    assert psc.list_packages(ctx).split("\n") == ["com.app.notes", "com.app.settings"]


def test_list_packages_falls_back_to_all_when_query_fails(monkeypatch):
    dev = FakeDevice([("pm list packages -f", "package:/a.apk=com.app.one\n")])
    monkeypatch.setattr(psc, "get_adb_device", lambda ctx: dev)
    ctx = MagicMock()
    ctx.device.mobile_platform = psc.DevicePlatform.ANDROID
    assert psc.list_packages(ctx) == "com.app.one"
