"""Pytest fixtures for uk_bin_collection tests."""

import pytest
import sys
from unittest.mock import MagicMock, AsyncMock


# Mock the uk_bin_collection package
class MockUKBinCollectionApp:
    """Mock UKBinCollectionApp class."""
    
    def __init__(self, *args, **kwargs):
        """Initialize mock app."""
        pass
    
    def execute(self, *args, **kwargs):
        """Mock execute method."""
        return {"bins": []}


# Create the mock module structure
@pytest.fixture(autouse=True)
def mock_uk_bin_collection_module():
    """Mock uk_bin_collection module to avoid import errors."""
    sys.modules['uk_bin_collection'] = MagicMock()
    sys.modules['uk_bin_collection.uk_bin_collection'] = MagicMock()
    collect_data_module = MagicMock()
    collect_data_module.UKBinCollectionApp = MockUKBinCollectionApp
    sys.modules['uk_bin_collection.uk_bin_collection.collect_data'] = collect_data_module
    
    yield
    
    # Clean up
    if 'uk_bin_collection' in sys.modules:
        del sys.modules['uk_bin_collection']
    if 'uk_bin_collection.uk_bin_collection' in sys.modules:
        del sys.modules['uk_bin_collection.uk_bin_collection']
    if 'uk_bin_collection.uk_bin_collection.collect_data' in sys.modules:
        del sys.modules['uk_bin_collection.uk_bin_collection.collect_data']


@pytest.fixture
def hass():
    """Mock Home Assistant instance."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = AsyncMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.loop = MagicMock()
    return hass