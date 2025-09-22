import json
from typing import Any
import httpx
from pydantic import BaseModel, ValidationError
from minitap.mobile_use.sdk.types.platform import (
    CreateTaskRunRequest,
    LLMProfileResponse,
    TaskResponse,
    TaskRunResponse,
    TaskRunStatus,
    UpdateTaskRunStatusRequest,
)
from minitap.mobile_use.utils.logger import get_logger

from minitap.mobile_use.config import LLMConfig, settings
from minitap.mobile_use.sdk.types.exceptions import PlatformServiceError
from minitap.mobile_use.sdk.types.task import (
    AgentProfile,
    PlatformTaskInfo,
    PlatformTaskRequest,
    TaskRequest,
)

logger = get_logger(__name__)

DEFAULT_PROFILE = "default"


class PlatformService:
    def __init__(self):
        if not settings.MINITAP_API_BASE_URL:
            raise PlatformServiceError(
                message="Please set MINITAP_API_BASE_URL environment variable.",
            )
        self._base_url = settings.MINITAP_API_BASE_URL

        if not settings.MINITAP_API_KEY:
            raise PlatformServiceError(
                message="Please set MINITAP_API_KEY environment variable.",
            )
        self._api_key = settings.MINITAP_API_KEY.get_secret_value()

        self._timeout = httpx.Timeout(timeout=120)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    async def create_task_run(self, request: PlatformTaskRequest) -> PlatformTaskInfo:
        try:
            logger.info(f"Getting task: {request.task}")
            response = await self._client.get(url=f"/tasks/{request.task}")
            response.raise_for_status()
            task_data = response.json()
            task = TaskResponse(**task_data)
            profile, agent_profile = await self._get_profile(
                profile_name=request.profile or DEFAULT_PROFILE,
            )
            task_request = TaskRequest(
                # Remote configuration
                max_steps=task.options.max_steps,
                goal=task.input_prompt,
                output_description=task.output_description,
                enable_remote_tracing=task.options.enable_tracing,
                profile=profile.name,
                # Local configuration
                record_trace=request.record_trace,
                trace_path=request.trace_path,
                llm_output_path=request.llm_output_path,
                thoughts_output_path=request.thoughts_output_path,
            )
            task_run = await self._create_task_run(task=task, profile=profile)
            return PlatformTaskInfo(
                task_request=task_request,
                llm_profile=agent_profile,
                task_run=task_run,
            )
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(message=f"Failed to get task: {e}")

    async def update_task_run_status(
        self,
        task_run_id: str,
        status: TaskRunStatus,
        message: str | None = None,
        output: Any | None = None,
    ) -> None:
        try:
            logger.info(f"Updating task run status for task run: {task_run_id}")

            sanitized_output: str | None = None
            if isinstance(output, dict):
                sanitized_output = json.dumps(output)
            elif isinstance(output, list):
                sanitized_output = json.dumps(output)
            elif isinstance(output, BaseModel):
                sanitized_output = output.model_dump_json()
            elif isinstance(output, str):
                sanitized_output = output
            else:
                sanitized_output = str(output)

            update = UpdateTaskRunStatusRequest(
                status=status,
                message=message,
                output=sanitized_output,
            )
            response = await self._client.patch(
                url=f"/task-runs/{task_run_id}/status",
                json=update.model_dump(),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(message=f"Failed to update task run status: {e}")

    async def _create_task_run(
        self,
        task: TaskResponse,
        profile: LLMProfileResponse,
    ) -> TaskRunResponse:
        try:
            logger.info(f"Creating task run for task: {task.name}")
            task_run = CreateTaskRunRequest(
                task_id=task.id,
                llm_profile_id=profile.id,
            )
            response = await self._client.post(url="/task-runs", json=task_run.model_dump())
            response.raise_for_status()
            task_run_data = response.json()
            return TaskRunResponse(**task_run_data)
        except ValidationError as e:
            raise PlatformServiceError(message=f"API response validation error: {e}")
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(message=f"Failed to create task run: {e}")

    async def _get_profile(self, profile_name: str) -> tuple[LLMProfileResponse, AgentProfile]:
        try:
            logger.info(f"Getting agent profile: {profile_name}")
            response = await self._client.get(url=f"/llm-profiles/{profile_name}")
            response.raise_for_status()
            profile_data = response.json()
            profile = LLMProfileResponse(**profile_data)
            agent_profile = AgentProfile(
                name=profile.name,
                llm_config=LLMConfig(**profile.llms),
            )
            return profile, agent_profile
        except ValidationError as e:
            raise PlatformServiceError(message=f"API response validation error: {e}")
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(message=f"Failed to get agent profile: {e}")
