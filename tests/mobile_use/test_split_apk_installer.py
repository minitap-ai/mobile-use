"""Tests for the split APK install-session helper."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from minitap.mobile_use.clients.split_apk_installer import (
    InstalledPackageInfo,
    SplitApkInstallError,
    install_split_apks,
    verify_foreground_package,
)


class FakeAdbDevice:
    """In-memory adbutils.AdbDevice stub.

    Records every ``shell`` invocation, matches commands against a caller-
    supplied ``responses`` dict (prefix match, longest-prefix wins), and lets
    tests assert both the sequence of commands and any teardown behaviour.
    """

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self._responses = dict(responses or {})
        self.shell_calls: list[str] = []
        self.pushed: list[tuple[str, str]] = []
        self.fail_on: str | None = None

    def shell(self, cmd: str) -> str:
        self.shell_calls.append(cmd)
        if self.fail_on is not None and self.fail_on in cmd:
            raise RuntimeError(f"forced adb failure on {cmd!r}")
        match = max(
            (prefix for prefix in self._responses if cmd.startswith(prefix)),
            key=len,
            default=None,
        )
        return self._responses[match] if match else ""

    def push(self, local: str, remote: str) -> None:
        self.pushed.append((local, remote))


def _make_apks(tmp_path: Path, splits: dict[str, bytes]) -> Path:
    path = tmp_path / "app.apks"
    with ZipFile(path, "w") as zf:
        for name, content in splits.items():
            zf.writestr(name, content)
    return path


def _happy_path_responses(
    package: str, version_code: int, split_names: list[str]
) -> dict[str, str]:
    return {
        "mkdir": "",
        "pm install-create": "Success: created install session [42]",
        "pm install-write": "Success",
        "pm install-commit": "Success",
        f"pm path {package}": "\n".join(f"package:/data/app/xxx/{n}" for n in split_names),
        f"dumpsys package {package}": "    versionCode=" + str(version_code) + " minSdk=24",
        "rm -rf": "",
    }


class TestInstallSplitApks:
    def test_happy_path_returns_verified_info(self, tmp_path: Path) -> None:
        apks = _make_apks(
            tmp_path, {"base.apk": b"AAA", "split_config.arm64_v8a.apk": b"BB"}
        )
        device = FakeAdbDevice(
            _happy_path_responses(
                "com.example", 7, ["base.apk", "split_config.arm64_v8a.apk"]
            )
        )

        info = install_split_apks(
            device,  # type: ignore[arg-type]
            apks,
            expected_package="com.example",
            expected_version_code=7,
        )

        assert info == InstalledPackageInfo(
            package="com.example",
            version_code=7,
            split_names=("base.apk", "split_config.arm64_v8a.apk"),
        )
        # Exactly two files pushed to the per-run device dir.
        assert len(device.pushed) == 2
        assert all(remote.startswith("/data/local/tmp/apks-") for _, remote in device.pushed)
        # Session opens once with the summed total, writes twice, commits once,
        # then wipes the tmp dir on success.
        assert any(c.startswith("pm install-create -r -S 5") for c in device.shell_calls)
        assert sum(c.startswith("pm install-write") for c in device.shell_calls) == 2
        assert any(c.startswith("pm install-commit 42") for c in device.shell_calls)
        assert any(c.startswith("rm -rf /data/local/tmp/apks-") for c in device.shell_calls)

    def test_no_apk_members_raises(self, tmp_path: Path) -> None:
        apks = _make_apks(tmp_path, {"README.txt": b"nope"})
        device = FakeAdbDevice()

        with pytest.raises(SplitApkInstallError, match="no APK members"):
            install_split_apks(
                device,  # type: ignore[arg-type]
                apks,
                expected_package="com.example",
                expected_version_code=1,
            )

    def test_install_write_failure_abandons_and_wipes(self, tmp_path: Path) -> None:
        apks = _make_apks(tmp_path, {"base.apk": b"A", "split.apk": b"B"})
        device = FakeAdbDevice(
            {
                "mkdir": "",
                "pm install-create": "Success: created install session [99]",
                "pm install-write": "Failure [INSTALL_FAILED_INVALID_APK]",
                "pm install-abandon": "Success",
                "rm -rf": "",
            }
        )

        with pytest.raises(SplitApkInstallError, match="INSTALL_FAILED_INVALID_APK"):
            install_split_apks(
                device,  # type: ignore[arg-type]
                apks,
                expected_package="com.example",
                expected_version_code=1,
            )

        # Failure teardown: session abandoned AND tmp dir wiped.
        assert any(c.startswith("pm install-abandon 99") for c in device.shell_calls)
        assert any(c.startswith("rm -rf /data/local/tmp/apks-") for c in device.shell_calls)

    def test_version_code_mismatch_raises_after_commit(self, tmp_path: Path) -> None:
        apks = _make_apks(tmp_path, {"base.apk": b"A"})
        device = FakeAdbDevice(
            {
                **_happy_path_responses("com.example", 7, ["base.apk"]),
                "dumpsys package com.example": "    versionCode=8 minSdk=24",
            }
        )

        with pytest.raises(SplitApkInstallError, match="versionCode mismatch"):
            install_split_apks(
                device,  # type: ignore[arg-type]
                apks,
                expected_package="com.example",
                expected_version_code=7,
            )

        # Verification failure still runs teardown so the session/tmp dir don't leak.
        assert any(c.startswith("pm install-abandon") for c in device.shell_calls) or any(
            c.startswith("rm -rf /data/local/tmp/apks-") for c in device.shell_calls
        )

    def test_package_absent_after_commit_raises(self, tmp_path: Path) -> None:
        apks = _make_apks(tmp_path, {"base.apk": b"A"})
        device = FakeAdbDevice(
            {
                **_happy_path_responses("com.example", 7, ["base.apk"]),
                "pm path com.example": "",
            }
        )

        with pytest.raises(SplitApkInstallError, match="not installed"):
            install_split_apks(
                device,  # type: ignore[arg-type]
                apks,
                expected_package="com.example",
                expected_version_code=7,
            )

    def test_traversal_members_are_filtered(self, tmp_path: Path) -> None:
        # Belt-and-suspenders: split_apks metadata already rejects these at upload,
        # but a malformed archive smuggled in later must never escape the tmp dir.
        apks = _make_apks(tmp_path, {"../evil.apk": b"X", "base.apk": b"A"})
        device = FakeAdbDevice(_happy_path_responses("com.example", 1, ["base.apk"]))

        install_split_apks(
            device,  # type: ignore[arg-type]
            apks,
            expected_package="com.example",
            expected_version_code=1,
        )
        # Only base.apk got pushed — traversal member was dropped.
        assert len(device.pushed) == 1
        assert device.pushed[0][1].endswith("/base.apk")


class TestVerifyForegroundPackage:
    def test_matching_focus_passes(self) -> None:
        focus_line = "mCurrentFocus=Window{... u0 com.example/.MainActivity}"
        device = FakeAdbDevice({"dumpsys window | grep mCurrentFocus": focus_line})
        verify_foreground_package(device, "com.example")  # type: ignore[arg-type]

    def test_wrong_focus_raises(self) -> None:
        focus_line = "mCurrentFocus=Window{... com.android.launcher3/.Launcher}"
        device = FakeAdbDevice({"dumpsys window | grep mCurrentFocus": focus_line})
        with pytest.raises(SplitApkInstallError, match="expected com.example"):
            verify_foreground_package(device, "com.example")  # type: ignore[arg-type]

    def test_empty_focus_raises(self) -> None:
        device = FakeAdbDevice({"dumpsys window | grep mCurrentFocus": ""})
        with pytest.raises(SplitApkInstallError, match="<empty>"):
            verify_foreground_package(device, "com.example")  # type: ignore[arg-type]
