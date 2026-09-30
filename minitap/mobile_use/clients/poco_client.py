import asyncio
import json
import math
import struct
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, FiniteFloat


class PocoConfig(BaseModel):
    """Poco-SDK endpoint for an instrumented local Android game."""

    package_name: str = Field(min_length=1, pattern=r"^\S+$")
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=5001, ge=1, le=65535)
    timeout: FiniteFloat = Field(default=2.0, gt=0)


class PocoPayload(BaseModel):
    name: str = ""
    type: str = ""
    text: str | None = None
    visible: bool = True
    pos: tuple[float, float] | None = None
    size: tuple[float, float] | None = None
    anchorPoint: tuple[float, float] = (0.5, 0.5)


class PocoNode(BaseModel):
    name: str = ""
    payload: PocoPayload = Field(default_factory=PocoPayload)
    children: list["PocoNode"] = Field(default_factory=list)


class PocoRpcError(BaseModel):
    code: int
    message: str


class PocoResponse(BaseModel):
    jsonrpc: Literal["2.0"]
    id: str
    result: PocoNode | None = None
    error: PocoRpcError | None = None


MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class PocoClient:
    """Serialize Poco-SDK Dump requests over a reusable TCP connection."""

    def __init__(self, config: PocoConfig):
        self.config = config
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def dump_hierarchy(self) -> PocoNode:
        async with asyncio.timeout(self.config.timeout):
            async with self._lock:
                if (self._reader is not None and self._reader.at_eof()) or (
                    self._writer is not None and self._writer.is_closing()
                ):
                    self._disconnect()
                reused = self._writer is not None
                try:
                    try:
                        return await self._request_hierarchy()
                    except (ConnectionError, asyncio.IncompleteReadError):
                        if not reused:
                            raise
                        self._disconnect()
                        return await self._request_hierarchy()
                except BaseException:
                    self._disconnect()
                    raise

    async def _request_hierarchy(self) -> PocoNode:
        if self._reader is None or self._writer is None:
            self._reader, self._writer = await asyncio.open_connection(
                self.config.host, self.config.port
            )
        request_id = str(uuid4())
        request = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": "Dump", "params": [True]}
        ).encode("utf-8")
        self._writer.write(struct.pack("<i", len(request)) + request)
        await self._writer.drain()
        length = struct.unpack("<i", await self._reader.readexactly(4))[0]
        if not 0 < length <= MAX_RESPONSE_BYTES:
            raise ValueError("Invalid Poco response length")
        response = PocoResponse.model_validate_json(await self._reader.readexactly(length))
        if response.id != request_id:
            raise ValueError("Poco response does not match the request")
        if response.error is not None:
            raise ValueError(f"Poco Dump failed: {response.error.message}")
        if response.result is None:
            raise ValueError("Poco response has no hierarchy")
        return response.result

    def _disconnect(self) -> asyncio.StreamWriter | None:
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
        return writer

    async def close(self) -> None:
        async with self._lock:
            writer = self._disconnect()
            if writer is not None:
                try:
                    async with asyncio.timeout(self.config.timeout):
                        await writer.wait_closed()
                except (OSError, TimeoutError):
                    pass


def normalize_hierarchy(root: PocoNode, width: int, height: int) -> list[dict]:
    """Convert screen-relative Poco nodes to flat Android selectors and pixel bounds."""
    if width <= 0 or height <= 0:
        raise ValueError("Screen dimensions must be positive")
    elements: list[dict] = []
    nodes = [root]
    while nodes:
        node = nodes.pop()
        payload = node.payload
        if not payload.visible:
            continue
        nodes.extend(reversed(node.children))
        if payload.pos is None or payload.size is None:
            continue
        size_x, size_y = payload.size
        if size_x <= 0 or size_y <= 0:
            continue
        pos_x, pos_y = payload.pos
        anchor_x, anchor_y = payload.anchorPoint
        left = (pos_x - anchor_x * size_x) * width
        top = (pos_y - anchor_y * size_y) * height
        right = left + size_x * width
        bottom = top + size_y * height
        if not all(math.isfinite(value) for value in (left, top, right, bottom)):
            continue
        x1 = round(max(0, min(width, left)))
        y1 = round(max(0, min(height, top)))
        x2 = round(max(0, min(width, right)))
        y2 = round(max(0, min(height, bottom)))
        if x1 >= x2 or y1 >= y2:
            continue
        name = node.name or payload.name
        elements.append(
            {
                "resource-id": name,
                "text": payload.text or "",
                "class": payload.type,
                "bounds": f"[{x1},{y1}][{x2},{y2}]",
            }
        )
    return elements
