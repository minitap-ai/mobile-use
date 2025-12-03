from abc import abstractmethod
from typing import Protocol

from pydantic import BaseModel

from minitap.mobile_use.controllers.types import Bounds, CoordinatesSelectorRequest, TapOutput


class ScreenDataResponse(BaseModel):
    base64: str
    elements: list
    width: int
    height: int
    platform: str


class MobileDeviceController(Protocol):
    @abstractmethod
    async def tap(
        self,
        coords: CoordinatesSelectorRequest,
        long_press: bool = False,
        long_press_duration: int = 1000,
    ) -> TapOutput:
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def swipe(
        self,
        start: CoordinatesSelectorRequest,
        end: CoordinatesSelectorRequest,
        duration: int = 400,
    ) -> str | None:
        """
        Swipe from start to end coordinates.
        Returns error message on failure, None on success.
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def screenshot(self) -> str:
        """Take a screenshot and return raw image data."""
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def input_text(self, text: str) -> bool:
        """
        Input text at the currently focused field.
        Returns True on success, False on failure.
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def launch_app(self, package_or_bundle_id: str) -> bool:
        """
        Launch an application by package name (Android) or bundle ID (iOS).
        Returns True on success, False on failure.
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def terminate_app(self, package_or_bundle_id: str | None) -> bool:
        """
        Terminate an application.
        Returns True on success, False on failure.
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def open_url(self, url: str) -> bool:
        """
        Open a URL.
        Returns True on success, False on failure.
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def press_back(self) -> bool:
        """
        Press the back button (Android) or equivalent gesture (iOS).
        Returns True on success, False on failure.
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def press_home(self) -> bool:
        """
        Press the home button.
        Returns True on success, False on failure.
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def get_ui_hierarchy(self) -> list[dict]:
        """
        Get the UI element hierarchy.
        Returns a list of UI elements with their properties.
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    def find_element(
        self,
        ui_hierarchy: list[dict],
        resource_id: str | None = None,
        text: str | None = None,
        index: int = 0,
    ) -> tuple[dict | None, Bounds | None, str | None]:
        """
        Find a UI element in the hierarchy.

        Returns:
            Tuple of (element_dict, bounds, error_message)
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up resources (e.g., stop companion processes)."""
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def erase_text(self, nb_chars: int | None = None) -> bool:
        """
        Erase the last nb_chars characters.
        Returns True on success, False on failure.
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def get_screen_data(self) -> "ScreenDataResponse":
        """
        Get screen data including screenshot (base64), UI hierarchy elements,
        screen dimensions, and platform.

        Returns:
            ScreenDataResponse with base64 screenshot, elements, width, height, platform
        """
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    def get_compressed_b64_screenshot(self, image_base64: str, quality: int = 50) -> str:
        """
        Compress a base64 image.
        Returns the compressed base64 image.
        """
        raise NotImplementedError("Subclasses must implement this method")
