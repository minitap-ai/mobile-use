#!/usr/bin/env python3
"""
Demo: Full W&B logging flow for mobile-use + android-world-runner.

Run:
    cd mobile-use && set -a && source .env && set +a
    uv run python scripts/demo_wandb_logging.py "Open Chrome and search for hello world"
"""

import asyncio
import sys
import os
import time
import logging

# Suppress noisy loggers
for logger_name in ["httpx", "httpcore", "urllib3", "openai", "wandb.sdk"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../android-world-runner/src"))

from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import Builders
from minitap.mobile_use.config import initialize_llm_config
from minitap.mobile_use.sdk.types.task import AgentProfile


async def run_with_wandb(goal: str):
    """Run a mobile-use task with full W&B logging."""
    
    from android_world_runner.observability.wandb_manager import WandbManager
    from android_world_runner.observability.config_builder import build_experiment_config
    
    # === RUNNER: Build experiment config ===
    config = build_experiment_config(
        experiment_type="e1_full_system",
        config_name="E1-04-full-system-demo",
        mobile_use_commit_sha="abc123",
        group="E1-architecture-buildup",
        job_type="full-system",
        use_planner=True,
        use_cortex=True,
        use_vision=True,
    )
    
    # === RUNNER: Create W&B run ===
    with WandbManager(
        experiment_type="e1_full_system",
        config=config,
        project="mobile-use-icml2026-demo",
        group="E1-architecture-buildup",
        job_type="full-system",
    ) as manager:
        
        if not manager.enabled:
            print("W&B disabled - set WANDB_API_KEY")
            return
        
        run_id = manager.get_run_id()
        print(f"\n{'='*60}")
        print(f"W&B: {manager.run.url}")
        print(f"{'='*60}\n")
        
        # === MOBILE-USE: Initialize agent ===
        llm_config = initialize_llm_config()
        agent_profile = AgentProfile(name="default", llm_config=llm_config)
        agent_config = Builders.AgentConfig.with_default_profile(profile=agent_profile)
        agent = Agent(config=agent_config.build())
        
        task_start = time.time()
        success = False
        
        try:
            await agent.init()
            
            # === RUNNER passes run_id to mobile-use ===
            task = agent.new_task(goal)
            task_request = task.build()
            task_request.wandb_run_id = run_id
            task_request.step_index = 0
            task_request.task_name = goal[:50]
            
            print(f"Goal: {goal}\n")
            
            # === MOBILE-USE: Run task (logs agent metrics to W&B) ===
            result = await agent.run_task(request=task_request)
            success = True
            print(f"\nResult: {result}")
            
        except KeyboardInterrupt:
            print("\nCancelled by user")
        except Exception as e:
            print(f"\nTask error: {e}")
        finally:
            await agent.clean()
        
        task_duration = time.time() - task_start
        
        # === RUNNER: Log task evaluation (success/failure) ===
        print(f"\n{'='*60}")
        print("Runner: Logging task evaluation...")
        
        manager.log_task_evaluation(
            task_idx=0,
            task_id="chrome_search_001",
            task_name=goal[:50],
            success=success,
            app="Chrome",
            category="single_app",
            duration_seconds=task_duration,
        )
        
        print(f"  success: {success}")
        print(f"  duration: {task_duration:.1f}s")
        print(f"{'='*60}")
        print(f"\nDashboard: {manager.run.url}")


def main():
    goal = sys.argv[1] if len(sys.argv) > 1 else "Open Chrome and search for hello world"
    asyncio.run(run_with_wandb(goal))


if __name__ == "__main__":
    main()
