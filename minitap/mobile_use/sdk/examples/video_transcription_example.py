"""
Video Transcription Example

This example demonstrates how to use the video recording tools to capture
and analyze video content from a mobile device screen.

The agent can:
1. Start a screen recording
2. Perform actions while recording
3. Stop the recording and analyze its content using Gemini models

Use case: Recording a video playing on the screen and transcribing its content.
"""

import asyncio

from minitap.mobile_use.config import LLM, LLMConfig, LLMConfigUtils, LLMWithFallback
from minitap.mobile_use.sdk.agent import Agent
from minitap.mobile_use.sdk.builders.agent_config_builder import AgentConfigBuilder
from minitap.mobile_use.sdk.types.agent import AgentConfig
from minitap.mobile_use.sdk.types.task import AgentProfile, TaskRequest


def get_video_capable_llm_config() -> LLMConfig:
    """
    Returns an LLM config with video_analyzer configured.

    The video_analyzer must use a video-capable Gemini model:
    - gemini-3-flash-preview (recommended - fast and capable)
    - gemini-3-pro-preview
    - gemini-2.5-flash
    - gemini-2.5-pro
    - gemini-2.0-flash
    """
    return LLMConfig(
        planner=LLMWithFallback(
            provider="openai",
            model="gpt-5-nano",
            fallback=LLM(provider="openai", model="gpt-5-mini"),
        ),
        orchestrator=LLMWithFallback(
            provider="openai",
            model="gpt-5-nano",
            fallback=LLM(provider="openai", model="gpt-5-mini"),
        ),
        contextor=LLMWithFallback(
            provider="openai",
            model="gpt-5-nano",
            fallback=LLM(provider="openai", model="gpt-5-mini"),
        ),
        cortex=LLMWithFallback(
            provider="openai",
            model="gpt-5",
            fallback=LLM(provider="openai", model="o4-mini"),
        ),
        executor=LLMWithFallback(
            provider="openai",
            model="gpt-5-nano",
            fallback=LLM(provider="openai", model="gpt-5-mini"),
        ),
        utils=LLMConfigUtils(
            outputter=LLMWithFallback(
                provider="openai",
                model="gpt-5-nano",
                fallback=LLM(provider="openai", model="gpt-5-mini"),
            ),
            hopper=LLMWithFallback(
                provider="openai",
                model="gpt-5-nano",
                fallback=LLM(provider="openai", model="gpt-5-mini"),
            ),
            video_analyzer=LLMWithFallback(
                provider="google",
                model="gemini-3-flash-preview",
                fallback=LLM(provider="google", model="gemini-2.5-flash"),
            ),
        ),
    )


async def main():
    config: AgentConfig = (
        AgentConfigBuilder()
        .add_profile(
            AgentProfile(
                name="VideoCapable",
                llm_config=get_video_capable_llm_config(),
            )
        )
        .with_video_recording_tools()
        .build()
    )

    agent = Agent(config=config)
    try:
        await agent.init()

        result = await agent.run_task(
            request=TaskRequest(
                goal="""
                1. Open YouTube app
                2. Search for "Python tutorial"
                3. Start recording the screen
                4. Play the first video
                5. Wait for the first 30 seconds of the video to play
                6. Stop recording and tell me what was said in the video
                """,
                profile="VideoCapable",
            )
        )
        print(f"Task result: {result}")
    finally:
        await agent.clean()


if __name__ == "__main__":
    asyncio.run(main())
