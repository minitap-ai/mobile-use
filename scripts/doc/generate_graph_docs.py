#!/usr/bin/env python3
"""
Script to generate graph visualization from the LangGraph structure.
This creates both a PNG image and a Mermaid markdown file.
It updates the README.md file with the generated graph.
"""

import asyncio
import sys
from pathlib import Path

from langchain_core.runnables.graph import CurveStyle, MermaidDrawMethod, NodeStyles
from langchain_core.runnables.graph_mermaid import draw_mermaid_png
from langgraph.graph.state import CompiledStateGraph

from minitap.mobile_use.config import get_default_llm_config
from minitap.mobile_use.context import DeviceContext, DevicePlatform

sys.path.append(str(Path(__file__).parent.parent))


async def generate_graph_docs():
    """Generate graph visualization as PNG."""
    from minitap.mobile_use.context import MobileUseContext
    from minitap.mobile_use.graph.graph import get_graph

    print("Loading graph structure...")
    ctx = MobileUseContext(
        trace_id="trace_id",
        device=DeviceContext(
            host_platform="LINUX",
            mobile_platform=DevicePlatform.ANDROID,
            device_id="device_id",
            device_width=1080,
            device_height=1920,
        ),
        llm_config=get_default_llm_config(),
    )

    print("Generating graph...")
    graph: CompiledStateGraph = await get_graph(ctx)

    png_path = Path(__file__).parent.parent.parent / "doc" / "graph.png"
    print(f"Generating PNG at {png_path}...")

    mermaid_text = graph.get_graph().draw_mermaid(
        node_colors=NodeStyles(
            default="fill:#d0c4f2,stroke:#b3b3b3,stroke-width:1px,color:#ffffff",
            first="fill:#9998e1,stroke:#b3b3b3,stroke-width:1px,color:#ffffff",
            last="fill:#9998e1,stroke:#b3b3b3,stroke-width:1px,color:#ffffff",
        ),
        curve_style=CurveStyle.LINEAR,
        frontmatter_config={
            "config": {
                "themeVariables": {
                    "lineColor": "#ffffff",
                },
            }
        },
    )

    draw_mermaid_png(
        mermaid_syntax=mermaid_text,
        output_file_path=str(png_path),
        draw_method=MermaidDrawMethod.API,
        background_color=None,
    )


if __name__ == "__main__":
    asyncio.run(generate_graph_docs())
