"""Test suite for IDB client iOS simulator integration.

These tests require:
1. macOS environment
2. iOS simulator (booted)
3. IDB companion installed (brew install idb-companion)
4. IOS_UDID environment variable set

Note: IDB companion is automatically started and stopped by the test fixtures.

Running locally:
    # Recommended: Use Makefile
    make test-ios

    # Or manually:
    # 1. Boot a simulator
    make simulator-up  # or: xcrun simctl boot <UDID>

    # 2. Set environment variable
    export IOS_UDID=$(cat .ios_udid)  # or: export IOS_UDID=<UDID>

    # 3. Run tests
    uv run pytest -v -m ios_simulator

Running all tests except iOS:
    make test
    # or: uv run pytest -v -m "not ios_simulator"
"""

import asyncio
import os

import pytest
import pytest_asyncio

from minitap.mobile_use.clients.idb_client import IdbClientWrapper


@pytest.fixture
def ios_udid():
    """Get iOS simulator UDID from environment variable.

    Requires IOS_UDID environment variable to be set.

    To run iOS tests:
        # Option 1: Use Makefile (recommended)
        make test-ios

        # Option 2: Set UDID manually
        export IOS_UDID=$(xcrun simctl list devices | grep Booted | \\
            head -n1 | sed -E 's/.*\\(([A-F0-9-]+)\\).*/\\1/')
        uv run pytest -v -m ios_simulator

        # Option 3: Boot simulator with Makefile
        make simulator-up
        export IOS_UDID=$(cat .ios_udid)
        uv run pytest -v -m ios_simulator
    """
    udid = os.getenv("IOS_UDID")
    if not udid:
        pytest.fail(
            "\n❌ IOS_UDID environment variable is not set!\n\n"
            "iOS simulator tests require a booted simulator UDID.\n\n"
            "Quick start:\n"
            "  1. Run: make simulator-up\n"
            "  2. Run: make test-ios\n\n"
            "Or manually:\n"
            "  1. Boot a simulator: xcrun simctl boot <UDID>\n"
            "  2. Set UDID: export IOS_UDID=<UDID>\n"
            "  3. Run tests: uv run pytest -v -m ios_simulator\n\n"
            "To find available simulators:\n"
            "  • make simulator-list\n"
            "  • xcrun simctl list devices\n"
            "  • idb list-targets\n"
        )
    return udid


@pytest_asyncio.fixture
async def idb_client(ios_udid):
    """Create IDB client wrapper with automatic companion management.

    The companion process is automatically started and stopped by the fixture.
    No manual companion startup is required.
    """
    client = IdbClientWrapper(udid=ios_udid)

    # Automatically initialize companion
    success = await client.init_companion()
    if not success:
        await client.cleanup()
        pytest.fail(f"Failed to initialize IDB companion for UDID: {ios_udid}")

    yield client

    # Automatically cleanup companion
    await client.cleanup()


@pytest.mark.asyncio
@pytest.mark.ios_simulator
async def test_idb_companion_init(idb_client):
    """Test IDB companion initialization.

    Note: Companion is already initialized by the fixture,
    this test verifies it's running and can be re-initialized.
    """
    # Companion already initialized by fixture, verify it's working
    # Calling init again should return True (already running)
    success = await idb_client.init_companion()
    assert success, "IDB companion should already be initialized"


@pytest.mark.asyncio
@pytest.mark.ios_simulator
async def test_idb_screenshot(idb_client):
    """Test IDB screenshot capture.

    Companion is automatically initialized by the fixture.
    """
    # Test screenshot with timeout
    try:
        screenshot_bytes = await asyncio.wait_for(
            idb_client.screenshot(),  # type: ignore
            timeout=10.0,
        )
        assert screenshot_bytes is not None, "Screenshot returned None"
        assert len(screenshot_bytes) > 0, "Screenshot has no data"
        assert isinstance(screenshot_bytes, bytes), "Screenshot is not bytes"
    except TimeoutError:
        pytest.fail("Screenshot timed out after 10 seconds")


@pytest.mark.asyncio
@pytest.mark.ios_simulator
async def test_idb_describe_all(idb_client):
    """Test IDB accessibility hierarchy retrieval.

    Companion is automatically initialized by the fixture.
    """
    # Test describe_all with timeout
    try:
        hierarchy = await asyncio.wait_for(
            idb_client.describe_all(),  # type: ignore
            timeout=10.0,
        )
        assert hierarchy is not None, "Hierarchy returned None"
        # IDB returns hierarchy as a list of accessibility elements
        assert isinstance(hierarchy, list), f"Hierarchy should be list, got {type(hierarchy)}"
        # Basic validation of hierarchy structure
        if hierarchy:
            assert len(hierarchy) > 0, "Hierarchy is empty"
    except TimeoutError:
        pytest.fail("describe_all timed out after 10 seconds")


@pytest.mark.asyncio
@pytest.mark.ios_simulator
async def test_idb_full_workflow(ios_udid):
    """Test complete IDB workflow: init -> screenshot -> hierarchy -> cleanup."""
    idb = IdbClientWrapper(udid=ios_udid)

    try:
        # Step 1: Initialize
        success = await idb.init_companion()
        assert success, "Failed to initialize companion"

        # Step 2: Screenshot
        screenshot_bytes = await asyncio.wait_for(
            idb.screenshot(),  # type: ignore
            timeout=10.0,
        )
        assert screenshot_bytes is not None
        assert len(screenshot_bytes) > 0

        # Step 3: Hierarchy
        hierarchy = await asyncio.wait_for(
            idb.describe_all(),  # type: ignore
            timeout=10.0,
        )
        assert hierarchy is not None
        # IDB returns hierarchy as a list of accessibility elements
        assert isinstance(hierarchy, list)
        assert len(hierarchy) > 0

    finally:
        await idb.cleanup()
