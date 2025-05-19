"""Pytest fixtures for uk_bin_collection tests."""

import os
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock

# Add the project root to the Python path so we can import custom_components
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Simple fixture for HomeAssistant
@pytest.fixture
def hass():
    """Mock Home Assistant instance."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = AsyncMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.loop = MagicMock()
    return hass