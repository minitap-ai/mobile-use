from pydantic import BaseModel, Field, model_validator

from minitap.mobile_use.utils.ui_hierarchy import ElementBounds


class Target(BaseModel):
    """
    A comprehensive locator for a UI element, supporting a fallback mechanism.
    """

    resource_id: str | None = Field(None, description="The resource-id of the element.")
    resource_id_index: int | None = Field(
        None,
        description="The zero-based index if multiple elements share the same resource-id.",
    )
    text: str | None = Field(
        None, description="The text content of the element (e.g., a label or placeholder)."
    )
    text_index: int | None = Field(
        None, description="The zero-based index if multiple elements share the same text."
    )
    coordinates: ElementBounds | None = Field(
        None, description="The x, y, width, and height of the element."
    )

    @model_validator(mode="after")
    def _default_indices(self):
        # Treat empty strings like “not provided”
        if (
            self.resource_id is not None and self.resource_id != ""
        ) and self.resource_id_index is None:
            self.resource_id_index = 0
        if (self.text is not None and self.text != "") and self.text_index is None:
            self.text_index = 0
        return self
