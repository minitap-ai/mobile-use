import asyncio

import pytest

from minitap.mobile_use.clients.cloud_device_client import CloudIosClient, ConnectionState


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False

    async def recv(self) -> str:
        await asyncio.Future()
        raise AssertionError("unreachable")

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_connect_cleans_up_when_device_info_fetch_fails(monkeypatch):
    websocket = FakeWebSocket()
    client = CloudIosClient(api_url="https://example.com", token="token")

    async def connect_websocket(_: str) -> FakeWebSocket:
        return websocket

    async def fail_device_info():
        raise RuntimeError("device info unavailable")

    monkeypatch.setattr(
        "minitap.mobile_use.clients.cloud_device_client.websockets.connect",
        connect_websocket,
    )
    monkeypatch.setattr(client, "_fetch_device_info", fail_device_info)

    with pytest.raises(RuntimeError, match="device info unavailable"):
        await client.connect()

    assert websocket.closed
    assert client.connection_state == ConnectionState.DISCONNECTED
    assert client._ws is None
    assert client._receive_task is None
    assert client._ping_task is None
