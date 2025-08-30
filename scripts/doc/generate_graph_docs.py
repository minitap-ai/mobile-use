#!/usr/bin/env python3
"""
Script to generate graph visualization from the LangGraph structure.
This creates both a PNG image and a Mermaid markdown file.
It updates the README.md file with the generated graph.
"""

import asyncio
import sys
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from minitap.mobile_use.clients.device_hardware_client import DeviceHardwareClient
from minitap.mobile_use.clients.screen_api_client import ScreenApiClient
from minitap.mobile_use.config import get_default_llm_config
from minitap.mobile_use.context import (
    DeviceContext,
    DevicePlatform,
)

sys.path.append(str(Path(__file__).parent.parent))


async def generate_graph_docs():
    """Generate graph visualization as PNG."""
    from minitap.mobile_use.context import MobileUseContext
    from minitap.mobile_use.graph.graph import get_graph

    print("⌛ Loading graph structure...")
    ctx = MobileUseContext(
        device=DeviceContext(
            host_platform="LINUX",
            mobile_platform=DevicePlatform.ANDROID,
            device_id="device_id",
            device_width=1080,
            device_height=1920,
        ),
        hw_bridge_client=DeviceHardwareClient(base_url="http://localhost:8000"),
        screen_api_client=ScreenApiClient(base_url="http://localhost:8000"),
        llm_config=get_default_llm_config(),
    )

    print("🧩 Generating graph...")
    graph: CompiledStateGraph = await get_graph(ctx)

    png_path = Path(__file__).parent.parent / "doc" / "graph.png"
    print(f"🖼️ Generating PNG at {png_path}...")
    graph.get_graph().draw_png(output_file_path=png_path.as_posix())
    print("✅ PNG generated successfully!")
    return png_path


if __name__ == "__main__":
    png_path = asyncio.run(generate_graph_docs())
