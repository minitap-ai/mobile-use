"""Service for managing cloud device (virtual mobile) task execution."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Literal

import httpx
from PIL import Image
from pydantic import BaseModel, Field

from minitap.mobile_use.config import settings
from minitap.mobile_use.sdk.types.exceptions import PlatformServiceError
from minitap.mobile_use.sdk.types.platform import TaskRunStatus
from minitap.mobile_use.sdk.types.task import PlatformTaskRequest
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class RunTaskRequest(BaseModel):
    """Request to run a task on a virtual mobile."""

    task_request: dict[str, Any] = Field(..., alias="taskRequest", description="Task request")


class RunTaskResponse(BaseModel):
    """Response from running a task on a virtual mobile."""

    task_run_id: str = Field(..., alias="taskRunId", description="ID of the task run")


class SubgoalTimelineItemResponse(BaseModel):
    """A subgoal timeline item."""

    name: str = Field(..., alias="name", description="Name of the subgoal")
    state: str = Field(..., alias="state", description="State of the subgoal")
    started_at: datetime | None = Field(
        None,
        alias="startedAt",
        description="Start time of the subgoal",
    )
    ended_at: datetime | None = Field(
        None,
        alias="endedAt",
        description="End time of the subgoal",
    )


class AgentThoughtTimelineItemResponse(BaseModel):
    """An agent thought timeline item."""

    agent: str = Field(..., alias="agent", description="Agent who thought")
    content: str = Field(..., alias="content", description="Content of the thought")
    timestamp: datetime = Field(..., alias="timestamp", description="Timestamp of the thought")


class TaskRunInfo(BaseModel):
    """Information about a task run."""

    id: str
    status: TaskRunStatus
    status_message: str | None = None
    output: str | dict[str, Any] | None = None


class TimelineItem(BaseModel):
    """A timeline item (subgoal or agent thought)."""

    timestamp: datetime
    content: str


VMState = Literal["Stopped", "Starting", "Ready", "Error", "Stopping", "Unknown"]


class VirtualMobileInfo(BaseModel):
    """Information about a virtual mobile."""

    id: str
    reference_name: str | None = None
    state: VMState
    message: str | None = None


class CloudMobileService:
    """
    Service for executing tasks on cloud mobiles.

    This service handles:
    - Starting and waiting for cloud mobiles to be ready
    - Triggering task execution via the Platform
    - Polling Platform API for task status and logs
    - Handling task cancellation
    - Timeout management for stalled tasks
    """

    def __init__(self, api_key: str | None = None, http_timeout_seconds: int = 120):
        self._platform_base_url = settings.MINITAP_BASE_URL

        if api_key:
            self._api_key = api_key
        elif settings.MINITAP_API_KEY:
            self._api_key = settings.MINITAP_API_KEY.get_secret_value()
        else:
            raise PlatformServiceError(
                message="Please provide an API key or set MINITAP_API_KEY environment variable.",
            )

        self._timeout = httpx.Timeout(timeout=http_timeout_seconds)
        self._client = httpx.AsyncClient(
            base_url=f"{self._platform_base_url}/api",
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    async def start_and_wait_for_ready(
        self,
        cloud_mobile_id: str,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 300.0,
    ) -> VirtualMobileInfo:
        """
        Start a cloud mobile by keeping it alive and wait for it to become ready.

        Args:
            cloud_mobile_id: ID of the cloud mobile to start
            poll_interval_seconds: Seconds between status polls (default: 5.0)
            timeout_seconds: Maximum time to wait for ready state (default: 300.0)

        Returns:
            VirtualMobileInfo with the final state

        Raises:
            PlatformServiceError: If the cloud mobile fails to start or times out
        """
        logger.info(f"Starting cloud mobile '{cloud_mobile_id}'")
        start_time = datetime.now(UTC)

        while True:
            # Check timeout
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            if elapsed > timeout_seconds:
                raise PlatformServiceError(
                    message=f"Timeout waiting for cloud mobile to be ready after {timeout_seconds}s"
                )

            # Trigger keep-alive to start the VM
            await self._keep_alive(cloud_mobile_id)
            # Get current status
            vm_info = await self._get_virtual_mobile_status(cloud_mobile_id)

            logger.info(
                f"Cloud mobile '{cloud_mobile_id}' status: {vm_info.state} - {vm_info.message}"
            )

            # Check if ready
            if vm_info.state == "Ready":
                logger.success(f"Cloud mobile '{cloud_mobile_id}' is ready")
                return vm_info

            # Check for error state
            if vm_info.state == "Error":
                raise PlatformServiceError(
                    message=f"Cloud mobile entered error state: {vm_info.message}"
                )

            # Wait before next poll
            await asyncio.sleep(poll_interval_seconds)

    async def _keep_alive(self, cloud_mobile_id: str) -> None:
        """Keep a cloud mobile alive to prevent idle shutdown."""
        try:
            response = await self._client.post(f"daas/virtual-mobiles/{cloud_mobile_id}/keep-alive")
            response.raise_for_status()
            logger.info(f"Keep-alive sent to cloud mobile '{cloud_mobile_id}'")
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(
                message="Failed to keep cloud mobile alive: "
                f"{e.response.status_code} - {e.response.text}"
            )

    async def _get_virtual_mobile_status(self, cloud_mobile_id: str) -> VirtualMobileInfo:
        """Get the current status of a cloud mobile."""
        try:
            response = await self._client.get(f"daas/virtual-mobiles/{cloud_mobile_id}")
            response.raise_for_status()
            data = response.json()

            return VirtualMobileInfo(
                id=data["id"],
                reference_name=data.get("referenceName"),
                state=data["state"].get("current", "Unknown"),
                message=data["state"].get("message", "Unknown"),
            )
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(
                message="Failed to get cloud mobile status: "
                f"{e.response.status_code} - {e.response.text}"
            )

    async def resolve_cloud_mobile_id(self, cloud_mobile_id_or_ref: str) -> str:
        """
        Resolve a cloud mobile identifier (ID or reference name) to a cloud mobile UUID.

        Uses the GetVirtualMobile endpoint which supports both UUID and reference name lookup.

        Args:
            cloud_mobile_id_or_ref: Either a cloud mobile UUID or reference name

        Returns:
            The cloud mobile UUID

        Raises:
            PlatformServiceError: If the cloud mobile is not found or resolution fails
        """
        try:
            response = await self._client.get(f"daas/virtual-mobiles/{cloud_mobile_id_or_ref}")
            response.raise_for_status()
            data = response.json()

            resolved_id = data["id"]
            logger.info(f"Resolved '{cloud_mobile_id_or_ref}' to UUID '{resolved_id}'")
            return resolved_id
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(
                message=f"Failed to resolve cloud mobile identifier '{cloud_mobile_id_or_ref}': "
                f"{e.response.status_code} - {e.response.text}"
            )

    async def run_task_on_cloud_mobile(
        self,
        cloud_mobile_id: str,
        request: PlatformTaskRequest,
        on_status_update: Callable[[TaskRunStatus, str | None], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        poll_interval_seconds: float = 2.0,
        stall_timeout_seconds: float = 300.0,
        locked_app_package: str | None = None,
    ) -> tuple[TaskRunStatus, str | None, Any | None]:
        """
        Run a task on a cloud mobile and wait for completion.

        Args:
            cloud_mobile_id: ID of the cloud mobile to run the task on
            request: Platform task request to execute
            on_status_update: Optional callback for status updates
            on_log: Optional callback for log messages
            poll_interval_seconds: Seconds between status polls (default: 2.0)
            stall_timeout_seconds: Timeout if no new timeline activity (default: 300.0)
            locked_app_package: Optional app package to lock for the task run

        Returns:
            Tuple of (final_status, error_message, output)

        Raises:
            PlatformServiceError: If the task execution fails
        """
        task_run_id: str | None = None
        try:
            # Step 1: Trigger the task run
            logger.info(f"Starting task on cloud mobile '{cloud_mobile_id}'")

            task_run_id = await self._trigger_task_run(
                cloud_mobile_id=cloud_mobile_id,
                request=request,
                locked_app_package=locked_app_package,
            )
            logger.info(f"Task run started: {task_run_id}")

            # Step 2: Poll for completion
            final_status, error, output = await self._poll_task_until_completion(
                cloud_mobile_id=cloud_mobile_id,
                task_run_id=task_run_id,
                on_status_update=on_status_update,
                on_log=on_log,
                poll_interval_seconds=poll_interval_seconds,
                stall_timeout_seconds=stall_timeout_seconds,
            )

            return final_status, error, output

        except asyncio.CancelledError:
            # Task was cancelled locally - propagate to the Platform
            logger.info("Task cancelled locally, propagating to the Platform")
            if task_run_id is not None:
                try:
                    await self.cancel_task_runs(cloud_mobile_id)
                except Exception as e:
                    logger.warning(f"Failed to propagate cancellation: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to run task on cloud device: {str(e)}")
            raise PlatformServiceError(message=f"Failed to run task on cloud device: {e}")

    async def _trigger_task_run(
        self,
        cloud_mobile_id: str,
        request: PlatformTaskRequest,
        locked_app_package: str | None = None,
    ) -> str:
        """Trigger a task run on the Platform and return the task run ID."""
        try:
            # Build the task request payload
            payload = RunTaskRequest(
                taskRequest={
                    "profile": request.profile,
                    "task": (
                        request.task if isinstance(request.task, str) else request.task.model_dump()
                    ),
                    "executionOrigin": request.execution_origin,
                    "lockedAppPackage": locked_app_package,
                }
            )

            response = await self._client.post(
                f"daas/virtual-mobiles/{cloud_mobile_id}/run-task",
                json=payload.model_dump(by_alias=True),
            )
            response.raise_for_status()

            result = RunTaskResponse.model_validate(response.json())
            return result.task_run_id

        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(message=f"Failed to trigger task run on the Platform: {e}")

    async def _poll_task_until_completion(
        self,
        cloud_mobile_id: str,
        task_run_id: str,
        on_status_update: Callable[[TaskRunStatus, str | None], None] | None,
        on_log: Callable[[str], None] | None,
        poll_interval_seconds: float,
        stall_timeout_seconds: float,
    ) -> tuple[TaskRunStatus, str | None, Any | None]:
        """
        Poll task run status until it completes, fails, or times out.

        Returns:
            Tuple of (final_status, error_message, output)
        """
        last_poll_time: datetime | None = None
        last_activity_time = datetime.now(UTC)
        current_status: TaskRunStatus = "pending"
        previous_status: TaskRunStatus | None = None

        while True:
            # Check for stall timeout
            now = datetime.now(UTC)
            time_since_last_activity = (now - last_activity_time).total_seconds()
            if time_since_last_activity > stall_timeout_seconds:
                error_msg = (
                    f"Task stalled: No activity for {stall_timeout_seconds} seconds. "
                    "The task is considered failed."
                )
                logger.error(f"{error_msg} (task_run_id: {task_run_id})")
                await self.cancel_task_runs(cloud_mobile_id)
                return "cancelled", error_msg, None

            # Fetch current task run status
            task_info = await self._get_task_run_status(task_run_id)
            current_status = task_info.status

            # Notify status update
            if previous_status != current_status and on_status_update:
                previous_status = current_status
                last_activity_time = now
                try:
                    on_status_update(
                        task_info.status,
                        task_info.status_message,
                    )
                except Exception as e:
                    logger.warning(f"Status update callback failed: {e}")

            # Check for subgoal updates
            subgoal_updates = await self._get_subgoal_updates(
                task_run_id=task_run_id,
                after_timestamp=last_poll_time,
            )

            # Check for new agent thoughts
            new_thoughts = await self._get_new_agent_thoughts(
                task_run_id=task_run_id,
                after_timestamp=last_poll_time,
            )

            updates = sorted(
                subgoal_updates + new_thoughts,
                key=lambda item: item.timestamp,
            )
            if updates:
                last_activity_time = now
                for update in updates:
                    if on_log:
                        try:
                            on_log(f"[{update.timestamp}] {update.content}")
                        except Exception as e:
                            logger.warning(f"Log callback failed: {e}")

            # Check if task is in terminal state
            if current_status in ["completed", "failed", "cancelled"]:
                logger.info(f"Task '{task_run_id}' reached terminal state: {current_status}")
                error = (
                    task_info.status_message if current_status in ["failed", "cancelled"] else None
                )
                return current_status, error, task_info.output

            # Wait before next poll
            last_poll_time = now
            await asyncio.sleep(poll_interval_seconds)

    async def _get_task_run_status(self, task_run_id: str) -> TaskRunInfo:
        """Get the current status of a task run."""
        try:
            response = await self._client.get(f"v1/task-runs/{task_run_id}")
            response.raise_for_status()
            data = response.json()

            output: str | dict[str, Any] | None = None
            raw_output = data.get("output")
            try:
                if raw_output is not None:
                    output = json.loads(raw_output)
            except json.JSONDecodeError:
                output = raw_output

            return TaskRunInfo(
                id=data["id"],
                status=data["status"],
                status_message=data.get("statusMessage"),
                output=output,
            )
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(message=f"Failed to get task run status: {e}")

    async def _get_subgoal_updates(
        self,
        task_run_id: str,
        after_timestamp: datetime | None,
    ) -> list[TimelineItem]:
        """Get new subgoals from the timeline after a specific timestamp."""
        try:
            started_subgoals = await self._get_filtered_subgoals(
                task_run_id=task_run_id,
                sort_by="started_at",
                sort_order="asc",
                after_timestamp=after_timestamp,
            )
            ended_subgoals = await self._get_filtered_subgoals(
                task_run_id=task_run_id,
                sort_by="ended_at",
                sort_order="asc",
                after_timestamp=after_timestamp,
            )
            items: list[TimelineItem] = []
            for subgoal in started_subgoals:
                if subgoal.started_at is None:
                    continue
                items.append(
                    TimelineItem(
                        timestamp=subgoal.started_at,
                        content=f"[START][{subgoal.name}] {subgoal.state}",
                    )
                )
            for subgoal in ended_subgoals:
                if subgoal.ended_at is None:
                    continue
                items.append(
                    TimelineItem(
                        timestamp=subgoal.ended_at,
                        content=f"[END][{subgoal.name}] {subgoal.state}",
                    )
                )
            return items
        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to get subgoals timeline: {e}")
            return []

    async def _get_filtered_subgoals(
        self,
        task_run_id: str,
        sort_by: str,
        sort_order: str,
        after_timestamp: datetime | None,
    ) -> list[SubgoalTimelineItemResponse]:
        params: dict[str, Any] = {
            "page": 1,
            "pageSize": 50,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        if after_timestamp:
            params["after"] = after_timestamp.isoformat()

        response = await self._client.get(
            f"v1/task-runs/{task_run_id}/subgoals/timeline",
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        subgoals = [
            SubgoalTimelineItemResponse.model_validate(item) for item in data.get("subgoals", [])
        ]
        return subgoals

    async def _get_new_agent_thoughts(
        self, task_run_id: str, after_timestamp: datetime | None
    ) -> list[TimelineItem]:
        """Get new agent thoughts from the timeline after a specific timestamp."""
        try:
            params: dict[str, Any] = {"page": 1, "pageSize": 50}
            if after_timestamp:
                params["after"] = after_timestamp.isoformat()

            response = await self._client.get(
                f"v1/task-runs/{task_run_id}/agent-thoughts/timeline",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            agent_thoughts = [
                AgentThoughtTimelineItemResponse.model_validate(item)
                for item in data.get("agentThoughts", [])
            ]

            items: list[TimelineItem] = []
            for thought in agent_thoughts:
                items.append(
                    TimelineItem(
                        timestamp=thought.timestamp,
                        content=f"[{thought.agent}] {thought.content}",
                    )
                )
            return items
        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to get agent thoughts timeline: {e}")
            return []

    async def cancel_task_runs(self, cloud_mobile_id: str) -> None:
        """Cancel all task runs on the Platform for a specific cloud mobile."""
        try:
            # Only one task can run on a cloud mobile at a time.
            # Therefore, cancelling all tasks running on it implies cancelling the task run.
            response = await self._client.post(
                f"v1/task-runs/virtual-mobile/{cloud_mobile_id}/cancel"
            )
            response.raise_for_status()
            logger.info(f"Task runs cancelled on cloud mobile '{cloud_mobile_id}'")
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(message=f"Failed to cancel task run: {e}")

    async def get_screenshot(self, cloud_mobile_id: str) -> Image.Image:
        """
        Get a screenshot from a cloud mobile.

        Args:
            cloud_mobile_id: ID of the cloud mobile to capture screenshot from

        Returns:
            Screenshot as PIL Image

        Raises:
            PlatformServiceError: If the screenshot capture fails
        """
        try:
            logger.info(f"Capturing screenshot from cloud mobile '{cloud_mobile_id}'")
            response = await self._client.get(f"daas/virtual-mobiles/{cloud_mobile_id}/screenshot")
            response.raise_for_status()

            # Convert bytes to PIL Image
            image = Image.open(BytesIO(response.content))

            size_bytes = len(response.content)
            logger.info(
                f"Screenshot captured from cloud mobile '{cloud_mobile_id}' ({size_bytes} bytes)"
            )
            return image
        except httpx.HTTPStatusError as e:
            raise PlatformServiceError(
                message=f"Failed to get screenshot from cloud mobile: "
                f"{e.response.status_code} - {e.response.text}"
            )
