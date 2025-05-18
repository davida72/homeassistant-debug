"""Pytest fixtures for uk_bin_collection tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock

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