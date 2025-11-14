from typing import Literal

from pydantic import BaseModel, Field


class ContextorOutput(BaseModel):
    """Output schema for the Contextor agent decision."""

    should_relaunch_app: bool = Field(..., description="Whether to relaunch the locked app")
    reasoning: str = Field(
        ..., description="Explanation of why we should or should not relaunch the app"
    )


class AppLockVerificationOutput(BaseModel):
    package_name: str = Field(..., description="Package name of the app that was verified")
    reasoning: str | None = Field(default=None, description="Reasoning for the decision")
    status: Literal["already_in_foreground", "relaunched", "allowed_deviation", "error"] = Field(
        ..., description="Status of the decision"
    )

    def to_message(self) -> str:
        msg = f"App {self.package_name}"
        match self.status:
            case "already_in_foreground":
                msg += " is already in foreground."
            case "relaunched":
                msg += " was relaunched."
            case "allowed_deviation":
                msg += " was allowed deviation."
            case "error":
                msg = f"Could not verify app lock for {self.package_name}."
        if self.reasoning:
            msg += f" {self.reasoning}"
        return msg
