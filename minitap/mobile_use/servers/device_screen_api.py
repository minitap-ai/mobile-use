import asyncio
import base64
import json
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sseclient import SSEClient

from minitap.mobile_use.servers.config import server_settings
from minitap.mobile_use.servers.utils import is_port_in_use

DEVICE_HARDWARE_BRIDGE_BASE_URL = server_settings.DEVICE_HARDWARE_BRIDGE_BASE_URL
DEVICE_HARDWARE_BRIDGE_API_URL = f"{DEVICE_HARDWARE_BRIDGE_BASE_URL}/api"

MAX_WAIT_TIME = 1

_latest_screen_data = None
_is_streaming_connected = False

_data_lock = threading.Lock()
_stream_thread = None
_stop_event = threading.Event()
_latest_screen_ts = None


def _stream_worker():
    global _latest_screen_data, _is_streaming_connected, _latest_screen_ts
    sse_url = f"{DEVICE_HARDWARE_BRIDGE_API_URL}/device-screen/sse"
    headers = {"Accept": "text/event-stream"}

    while not _stop_event.is_set():
        try:
            with requests.get(sse_url, stream=True, headers=headers) as response:
                response.raise_for_status()
                print("--- Stream connected, listening for events... ---")
                with _data_lock:
                    _is_streaming_connected = True
                event_source = (chunk for chunk in response.iter_content())
                client = SSEClient(event_source)
                for event in client.events():
                    if _stop_event.is_set():
                        break
                    if event.event == "message" and event.data:
                        data = json.loads(event.data)
                        screenshot_path = data.get("screenshot")
                        elements = data.get("elements", [])
                        width = data.get("width")
                        height = data.get("height")
                        platform = data.get("platform")

                        image_url = f"{DEVICE_HARDWARE_BRIDGE_BASE_URL}{screenshot_path}"
                        image_response = requests.get(image_url)
                        image_response.raise_for_status()
                        base64_image = base64.b64encode(image_response.content).decode("utf-8")
                        base64_data_url = f"data:image/png;base64,{base64_image}"

                        with _data_lock:
                            _latest_screen_data = {
                                "base64": base64_data_url,
                                "elements": elements,
                                "width": width,
                                "height": height,
                                "platform": platform,
                            }
                            _latest_screen_ts = datetime.now(UTC)

        except Exception as e:
            print(f"Connection error in stream worker: {e}. Retrying in 2 seconds...")
            with _data_lock:
                _is_streaming_connected = False
                _latest_screen_data = None

            time.sleep(2)


def start_stream():
    global _stream_thread
    if _stream_thread is None or not _stream_thread.is_alive():
        _stop_event.clear()
        _stream_thread = threading.Thread(target=_stream_worker, daemon=True)
        _stream_thread.start()
        print("--- Background screen streaming started ---")


def stop_stream():
    global _stream_thread, _is_streaming_connected
    if _stream_thread and _stream_thread.is_alive():
        _stop_event.set()
        with _data_lock:
            _is_streaming_connected = False
        _stream_thread.join(timeout=2)
        print("--- Background screen streaming stopped ---")


@asynccontextmanager
async def lifespan(_: FastAPI):
    start_stream()
    yield
    stop_stream()


app = FastAPI(lifespan=lifespan)


def get_latest_data():
    """Helper to get the latest data safely, with retries."""
    max_wait_time = 30  # seconds
    retry_delay = 2  # seconds
    start_time = time.time()

    while time.time() - start_time < max_wait_time:
        with _data_lock:
            if _latest_screen_data is not None:
                return _latest_screen_data
        time.sleep(retry_delay)

    raise HTTPException(
        status_code=503,
        detail="Screen data is not yet available after multiple retries.",
    )


@app.get("/screen-info")
async def get_screen_info():
    now = datetime.now(UTC)
    waited_for_seconds = 0
    while not _latest_screen_ts or _latest_screen_ts < now:
        wait_for_seconds = 0.05
        await asyncio.sleep(wait_for_seconds)
        waited_for_seconds += wait_for_seconds
        if waited_for_seconds >= MAX_WAIT_TIME:
            break
    data = get_latest_data()
    return JSONResponse(content=data)


@app.get("/health")
async def health_check():
    """Check if the Maestro Studio server is healthy."""
    health_url = f"{DEVICE_HARDWARE_BRIDGE_API_URL}/banner-message"
    try:
        response = requests.get(health_url, timeout=5)
        response.raise_for_status()
        with _data_lock:
            if _latest_screen_data is None:
                raise HTTPException(
                    status_code=503,
                    detail="Screen data is not yet available after multiple retries.",
                )
        return JSONResponse(content=response.json())
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Maestro Studio not available: {e}")


@app.get("/streaming-status")
async def streaming_status():
    """Check if the SSE streaming connection is active."""
    with _data_lock:
        return JSONResponse(
            content={
                "is_streaming_connected": _is_streaming_connected,
                "has_screen_data": _latest_screen_data is not None,
            }
        )


def start():
    if not is_port_in_use(server_settings.DEVICE_SCREEN_API_PORT):
        uvicorn.run(app, host="0.0.0.0", port=server_settings.DEVICE_SCREEN_API_PORT)
        return True
    print(f"Device screen API is already running on port {server_settings.DEVICE_SCREEN_API_PORT}")
    return False
