from pydantic import BaseModel, ConfigDict, Field


class TapOutput(BaseModel):
    """Output from tap operations."""

    error: str | None = Field(default=None, description="Error message if tap failed")


class Bounds(BaseModel):
    """Represents the bounds of a UI element."""

    x1: int
    y1: int
    x2: int
    y2: int

    def get_center(self) -> "CoordinatesSelectorRequest":
        """Get the center point of the bounds."""
        return CoordinatesSelectorRequest(
            x=(self.x1 + self.x2) // 2,
            y=(self.y1 + self.y2) // 2,
        )


class CoordinatesSelectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int
    y: int

    def to_str(self):
        return f"{self.x}, {self.y}"


class PercentagesSelectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """
    0%,0%        # top-left corner
    100%,100%    # bottom-right corner
    50%,50%      # center
    """

    x_percent: int = Field(ge=0, le=100, description="X percentage (0-100)")
    y_percent: int = Field(ge=0, le=100, description="Y percentage (0-100)")

    def to_str(self):
        return f"{self.x_percent}%, {self.y_percent}%"

    def to_coords(self, width: int, height: int) -> CoordinatesSelectorRequest:
        """Convert percentages to pixel coordinates."""
        x = min(max(int(width * self.x_percent / 100), 0), max(0, width - 1))
        y = min(max(int(height * self.y_percent / 100), 0), max(0, height - 1))
        return CoordinatesSelectorRequest(x=x, y=y)


class SwipeStartEndCoordinatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: CoordinatesSelectorRequest
    end: CoordinatesSelectorRequest

    def to_dict(self):
        return {"start": self.start.to_str(), "end": self.end.to_str()}


class SwipeStartEndPercentagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: PercentagesSelectorRequest
    end: PercentagesSelectorRequest

    def to_dict(self):
        return {"start": self.start.to_str(), "end": self.end.to_str()}

    def to_coords(self, width: int, height: int) -> SwipeStartEndCoordinatesRequest:
        """Convert percentage-based swipe to coordinate-based swipe."""
        return SwipeStartEndCoordinatesRequest(
            start=self.start.to_coords(width, height),
            end=self.end.to_coords(width, height),
        )


class SwipeRequest(BaseModel):
    """
    Swipe from start to end position using coordinates or percentages.
    """

    model_config = ConfigDict(extra="forbid")
    swipe_mode: SwipeStartEndCoordinatesRequest | SwipeStartEndPercentagesRequest = Field(
        description="Start and end positions. Use EITHER (x, y) OR (x_percent, y_percent)."
    )
    duration: int | None = Field(
        default=None,
        description="Swipe duration in ms. If not provided, tool functions default to 400ms.",
        ge=1,
        le=10000,
    )

    def to_dict(self):
        res = {}
        if isinstance(
            self.swipe_mode,
            SwipeStartEndCoordinatesRequest | SwipeStartEndPercentagesRequest,
        ):
            res |= self.swipe_mode.to_dict()
        if self.duration:
            res |= {"duration": self.duration}
        return res
