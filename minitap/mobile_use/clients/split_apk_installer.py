"""Install a flat ``.apks`` archive via one PackageManager install session.

Limrun's per-instance ``initialAssets`` installer only accepts a single APK,
so a split APK archive must be pushed and installed manually against an
already-established ADB session. This module runs the standard Android split
install sequence (``pm install-create`` / ``install-write`` / ``install-commit``)
and abandons the session + wipes the device tmp dir on any failure.

Callers wrap this in ``asyncio.to_thread`` — adbutils is synchronous.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from adbutils import AdbDevice

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

_DEVICE_TMP_ROOT = "/data/local/tmp"
_SESSION_ID_RE = re.compile(r"\[(\d+)\]")
_VERSION_CODE_RE = re.compile(r"versionCode=(\d+)")


class SplitApkInstallError(RuntimeError):
    """Raised when the split-APK install session or its verification fails."""


@dataclass(frozen=True)
class InstalledPackageInfo:
    """Post-install verification snapshot."""

    package: str
    version_code: int
    split_names: tuple[str, ...]


def install_split_apks(
    device: AdbDevice,
    apks_path: Path,
    *,
    expected_package: str,
    expected_version_code: int,
) -> InstalledPackageInfo:
    """Install every APK inside a flat ``.apks`` archive as one PM session.

    Extracts the archive to a local temp dir, mirrors it under a per-run
    ``/data/local/tmp/apks-<uuid>/`` on-device dir, opens an install session
    sized to the total, install-writes each split, commits, then verifies
    package / versionCode / installed splits. On any failure the session is
    abandoned and both temp dirs are wiped before re-raising.
    """
    run_id = uuid.uuid4().hex[:12]
    device_dir = f"{_DEVICE_TMP_ROOT}/apks-{run_id}"
    session_id: str | None = None
    try:
        with tempfile.TemporaryDirectory(prefix=f"apks-{run_id}-") as local_dir:
            splits = _extract_flat_archive(apks_path, Path(local_dir))
            total_bytes = sum(s.stat().st_size for s in splits)
            _shell_ok(device, f"mkdir -p {device_dir}")
            session_id = _create_session(device, total_bytes)
            for split in splits:
                remote = f"{device_dir}/{split.name}"
                device.push(str(split), remote)
                _install_write(device, session_id, split, remote)
            _commit(device, session_id)
        info = _verify(device, expected_package, expected_version_code)
        _rm_rf_quietly(device, device_dir)
        return info
    except Exception:
        if session_id is not None:
            _abandon_quietly(device, session_id)
        _rm_rf_quietly(device, device_dir)
        raise


def verify_foreground_package(device: AdbDevice, expected_package: str) -> None:
    """Check that ``expected_package`` owns the currently focused window.

    Called after ``am start`` to confirm the freshly-installed app actually
    launches. Raises :class:`SplitApkInstallError` when the focus is empty
    or held by a different package (typically the launcher).
    """
    focus = str(device.shell("dumpsys window | grep mCurrentFocus")).strip()
    if expected_package not in focus:
        raise SplitApkInstallError(
            f"expected {expected_package} in foreground, got: {focus or '<empty>'}"
        )


def _extract_flat_archive(archive: Path, dest: Path) -> list[Path]:
    """Materialise every ``.apk`` member of the archive as a file under ``dest``.

    The archive is assumed already-validated (flat, no traversal) by
    testing-service's ``extract_split_apks_metadata`` at upload time; we only
    filter members defensively so a malformed archive smuggled in later can't
    escape the directory.
    """
    extracted: list[Path] = []
    with ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir() or "/" in name or "\\" in name or not name.lower().endswith(".apk"):
                continue
            out = dest / name
            with zf.open(info) as src, open(out, "wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
            extracted.append(out)
    if not extracted:
        raise SplitApkInstallError(f"no APK members in archive {archive}")
    return extracted


def _create_session(device: AdbDevice, total_bytes: int) -> str:
    out = _shell_ok(device, f"pm install-create -r -S {total_bytes}")
    match = _SESSION_ID_RE.search(out)
    if match is None:
        raise SplitApkInstallError(f"pm install-create did not return a session id: {out!r}")
    return match.group(1)


def _install_write(device: AdbDevice, session_id: str, split: Path, remote_path: str) -> None:
    tag = split.stem  # e.g. "base", "split_config.arm64_v8a"
    size = split.stat().st_size
    _shell_ok(device, f"pm install-write -S {size} {session_id} {tag} {remote_path}")


def _commit(device: AdbDevice, session_id: str) -> None:
    _shell_ok(device, f"pm install-commit {session_id}")


def _verify(
    device: AdbDevice,
    expected_package: str,
    expected_version_code: int,
) -> InstalledPackageInfo:
    paths = str(device.shell(f"pm path {expected_package}")).strip()
    if not paths or "package:" not in paths:
        raise SplitApkInstallError(f"package {expected_package} not installed after commit")
    split_names = tuple(
        sorted(Path(line.removeprefix("package:")).name for line in paths.splitlines())
    )
    dump = str(device.shell(f"dumpsys package {expected_package} | grep versionCode")).strip()
    version_match = _VERSION_CODE_RE.search(dump)
    if version_match is None:
        raise SplitApkInstallError(f"versionCode not found for {expected_package}: {dump!r}")
    version_code = int(version_match.group(1))
    if version_code != expected_version_code:
        raise SplitApkInstallError(
            f"versionCode mismatch for {expected_package}: "
            f"expected {expected_version_code}, got {version_code}"
        )
    return InstalledPackageInfo(
        package=expected_package, version_code=version_code, split_names=split_names
    )


def _shell_ok(device: AdbDevice, cmd: str) -> str:
    """Run a shell command and raise on non-``Success`` PM output.

    ``pm install-*`` writes ``Success`` to stdout on success and a
    ``Failure [reason]`` line on failure while still exiting 0, so we cannot
    trust the exit code alone. Non-``pm`` callers get the raw output back.
    """
    out = str(device.shell(cmd)).strip()
    if cmd.startswith("pm install") and "Success" not in out:
        raise SplitApkInstallError(f"{cmd!r} failed: {out or '<empty>'}")
    return out


def _abandon_quietly(device: AdbDevice, session_id: str) -> None:
    try:
        device.shell(f"pm install-abandon {session_id}")
    except Exception as exc:  # noqa: BLE001 — best-effort teardown
        logger.warning("split_apk.abandon_failed", session_id=session_id, error=str(exc))


def _rm_rf_quietly(device: AdbDevice, remote_dir: str) -> None:
    try:
        device.shell(f"rm -rf {remote_dir}")
    except Exception as exc:  # noqa: BLE001 — best-effort teardown
        logger.warning("split_apk.rm_failed", remote_dir=remote_dir, error=str(exc))
