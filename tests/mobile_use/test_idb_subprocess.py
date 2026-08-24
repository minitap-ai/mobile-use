import asyncio

import pytest

from minitap.mobile_use.clients.idb_client import IdbClientWrapper


class HangingProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.Event().wait()
        return b"", b""

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    async def wait(self) -> int:
        self.waited = True
        assert self.returncode is not None
        return self.returncode


@pytest.mark.asyncio
async def test_describe_all_cleans_up_cancelled_subprocess(monkeypatch: pytest.MonkeyPatch):
    process = HangingProcess()

    async def create_subprocess(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess)
    task = asyncio.create_task(IdbClientWrapper(udid="simulator").describe_all())
    await asyncio.sleep(0)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated
    assert process.waited
