"""
ADB WebSocket tunnel implementation.

Bridges local TCP connections to a remote ADB server via WebSocket.
This replaces the need for the `lim` CLI for ADB tunneling.

The tunnel runs in a dedicated thread with its own event loop to ensure
it cannot be blocked by synchronous operations in the main thread.

Based on the Go SDK implementation which:
1. Creates a TCP listener
2. Accepts TCP connections from ADB
3. Dials the WebSocket
4. Forwards traffic bidirectionally
"""

import asyncio
import socket
import threading
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import websockets
from websockets.asyncio.client import ClientConnection

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

BUFFER_SIZE = 32 * 1024  # 32KB, same as Go SDK
PING_INTERVAL = 30  # seconds


class AdbTunnel:
    """
    ADB tunnel that bridges local TCP connections to a remote WebSocket endpoint.

    Runs in a dedicated thread with its own event loop to ensure the tunnel
    cannot be blocked by synchronous operations in the caller's thread.

    Usage:
        tunnel = AdbTunnel(remote_url, token)
        addr = await tunnel.start()  # Returns "127.0.0.1:PORT"
        # Use addr with ADB: adb connect 127.0.0.1:PORT
        await tunnel.stop()
    """

    def __init__(self, remote_url: str, token: str):
        """
        Initialize the ADB tunnel.

        Args:
            remote_url: WebSocket URL for the remote ADB endpoint
            token: Bearer token for authentication
        """
        self.remote_url = remote_url
        self.token = token

        self._local_port: int | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()
        self._stop_event: asyncio.Event | None = None

    @property
    def local_addr(self) -> str:
        """Get the local address to connect ADB to."""
        if self._local_port is None:
            raise RuntimeError("Tunnel not started")
        return f"127.0.0.1:{self._local_port}"

    @property
    def local_port(self) -> int:
        """Get the local port number."""
        if self._local_port is None:
            raise RuntimeError("Tunnel not started")
        return self._local_port

    async def start(self) -> str:
        """
        Start the ADB tunnel in a dedicated thread.

        Returns:
            The local address (host:port) to connect ADB to.
        """
        if self._thread is not None and self._thread.is_alive():
            return self.local_addr

        # Create listener in main thread to get the port immediately
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        listener.setblocking(False)
        self._local_port = listener.getsockname()[1]

        logger.info(f"ADB tunnel listening on {self.local_addr}")

        # Start tunnel thread
        self._thread = threading.Thread(
            target=self._run_in_thread,
            args=(listener,),
            name=f"adb-tunnel-{self._local_port}",
            daemon=True,
        )
        self._thread.start()

        # Wait for thread to initialize its event loop
        self._started.wait(timeout=5.0)
        if not self._started.is_set():
            await self.stop()
            raise RuntimeError("Tunnel thread failed to start")

        return self.local_addr

    async def stop(self) -> None:
        """Stop the ADB tunnel and cleanup resources."""
        if self._loop and self._stop_event:
            # Signal the tunnel loop to stop
            self._loop.call_soon_threadsafe(self._stop_event.set)

        if self._thread and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, 5.0)
            if self._thread.is_alive():
                logger.warning("ADB tunnel thread did not stop within 5s")

        self._thread = None
        self._loop = None
        self._stop_event = None
        logger.info("ADB tunnel stopped")

    def _run_in_thread(self, listener: socket.socket) -> None:
        """Run the tunnel event loop in a dedicated thread."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._stop_event = asyncio.Event()
            self._started.set()

            self._loop.run_until_complete(self._run_tunnel(listener))
        except Exception as e:
            logger.error(f"Tunnel thread error: {e}")
        finally:
            listener.close()
            if self._loop:
                self._loop.close()

    async def _run_tunnel(self, listener: socket.socket) -> None:
        """Run the tunnel - accept TCP connections and bridge to WebSocket."""
        loop = asyncio.get_event_loop()
        connection_tasks: list[asyncio.Task] = []

        stop_event = self._stop_event
        assert stop_event is not None

        logger.debug("Tunnel: ready to accept connections")

        while not stop_event.is_set():
            try:
                # Use wait_for to periodically check stop_event
                try:
                    tcp_conn, addr = await asyncio.wait_for(
                        loop.sock_accept(listener),
                        timeout=1.0,
                    )
                except TimeoutError:
                    # Check if we should stop
                    continue

                logger.debug(f"Tunnel: new TCP connection from {addr}")

                task = asyncio.create_task(
                    self._handle_connection(tcp_conn, loop),
                    name=f"conn-{addr[1]}",
                )
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                connection_tasks.append(task)
                connection_tasks = [t for t in connection_tasks if not t.done()]

            except Exception as e:
                if not stop_event.is_set():
                    logger.error(f"Tunnel accept error: {e}")
                break

        # Cleanup pending connections
        for task in connection_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _handle_connection(
        self,
        tcp_conn: socket.socket,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Handle a single TCP connection."""
        tcp_conn.setblocking(False)

        ws: ClientConnection | None = None
        try:
            logger.debug(f"Connecting to WebSocket: {self.remote_url[:80]}...")
            ws = await websockets.connect(
                self.remote_url,
                additional_headers={"Authorization": f"Bearer {self.token}"},
                ping_interval=PING_INTERVAL,
                ping_timeout=10,
            )
            logger.debug("WebSocket connected to remote ADB")
            await self._bridge(tcp_conn, ws, loop)
        except Exception as e:
            logger.error(f"Connection error: {e}")
        finally:
            if ws is not None:
                await ws.close()
            tcp_conn.close()
            logger.debug("Connection closed")

    async def _bridge(
        self,
        tcp_conn: socket.socket,
        ws: ClientConnection,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Bridge TCP and WebSocket bidirectionally."""

        stop_event = self._stop_event
        assert stop_event is not None

        async def tcp_to_ws() -> None:
            """Forward data from TCP to WebSocket."""
            msg_count = 0
            try:
                while not stop_event.is_set():
                    try:
                        data = await asyncio.wait_for(
                            loop.sock_recv(tcp_conn, BUFFER_SIZE),
                            timeout=1.0,
                        )
                    except TimeoutError:
                        continue
                    except (OSError, ConnectionError) as e:
                        logger.debug(f"tcp->ws: recv error after {msg_count} msgs: {e}")
                        break
                    if not data:
                        logger.debug(f"tcp->ws: closed by client after {msg_count} msgs")
                        break
                    msg_count += 1
                    logger.debug(f"tcp->ws: [{msg_count}] sending {len(data)} bytes")
                    await ws.send(data)
                logger.debug(f"tcp->ws: loop ended after {msg_count} messages")
            except asyncio.CancelledError:
                logger.debug(f"tcp->ws: cancelled after {msg_count} messages")
                raise
            except Exception as e:
                logger.error(f"tcp->ws: error after {msg_count} messages: {e}")

        async def ws_to_tcp() -> None:
            """Forward data from WebSocket to TCP."""
            msg_count = 0
            try:
                logger.debug("ws->tcp: starting message loop")
                async for message in ws:
                    if stop_event.is_set():
                        break
                    if isinstance(message, bytes) and message:
                        msg_count += 1
                        logger.debug(f"ws->tcp: [{msg_count}] received {len(message)} bytes")
                        await loop.sock_sendall(tcp_conn, message)
                    elif isinstance(message, str):
                        logger.debug(f"ws->tcp: received string: {message[:100]}")
                logger.debug(f"ws->tcp: loop ended after {msg_count} messages")
            except asyncio.CancelledError:
                logger.debug(f"ws->tcp: cancelled after {msg_count} messages")
                raise
            except Exception as e:
                logger.error(f"ws->tcp: error after {msg_count} messages: {e}")

        tcp_task = asyncio.create_task(tcp_to_ws())
        ws_task = asyncio.create_task(ws_to_tcp())

        done, pending = await asyncio.wait(
            [tcp_task, ws_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@asynccontextmanager
async def adb_tunnel(remote_url: str, token: str) -> AsyncGenerator[AdbTunnel, None]:
    """
    Context manager for creating and managing an ADB tunnel.

    Args:
        remote_url: WebSocket URL for the remote ADB endpoint
        token: Bearer token for authentication

    Yields:
        AdbTunnel instance with the tunnel running

    Example:
        async with adb_tunnel(ws_url, token) as tunnel:
            # Connect ADB to tunnel.local_addr
            adb_client = AdbClient()
            adb_client.connect(tunnel.local_addr)
    """
    tunnel = AdbTunnel(remote_url, token)
    try:
        await tunnel.start()
        yield tunnel
    finally:
        await tunnel.stop()
