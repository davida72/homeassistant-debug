"""Test UK Bin Collection integration initialization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.uk_bin_collection import (
    async_reload_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.uk_bin_collection.const import DOMAIN

from .common_utils import MockConfigEntry


@pytest.fixture
def config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test Bins",
            "council": "TestCouncil",
            "url": "https://example.com",
            "update_interval": 60,
        },
        entry_id="test_init",
    )


@pytest.mark.asyncio
async def test_setup_entry(hass, config_entry):
    """Test setting up the integration."""
    config_entry.add_to_hass(hass)
    
    # Mock the forward_entry_setup calls
    with patch("homeassistant.config_entries.ConfigEntries.async_forward_entry_setup", return_value=True):
        assert await async_setup_entry(hass, config_entry)
        
        # Check that the entry was set up correctly
        assert DOMAIN in hass.data
        assert config_entry.entry_id in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_setup_entry_fails(hass, config_entry):
    """Test setting up the integration with failure."""
    config_entry.add_to_hass(hass)
    
    # Mock the forward_entry_setup calls to fail
    with patch("homeassistant.config_entries.ConfigEntries.async_forward_entry_setup", side_effect=Exception("Test error")):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, config_entry)


@pytest.mark.asyncio
async def test_unload_entry(hass, config_entry):
    """Test unloading the integration."""
    config_entry.add_to_hass(hass)
    
    # Set up the entry first
    hass.data[DOMAIN] = {config_entry.entry_id: {}}
    
    # Mock the forward_entry_unload calls
    with patch("homeassistant.config_entries.ConfigEntries.async_forward_entry_unload", return_value=True):
        assert await async_unload_entry(hass, config_entry)
        
        # Check that the entry was unloaded correctly
        assert config_entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_reload_entry(hass, config_entry):
    """Test reloading the integration."""
    config_entry.add_to_hass(hass)
    
    # Set up the entry first
    hass.data[DOMAIN] = {config_entry.entry_id: {}}
    
    # Mock the unload and setup methods
    with patch("custom_components.uk_bin_collection.async_unload_entry", return_value=True), \
         patch("custom_components.uk_bin_collection.async_setup_entry", return_value=True):
        await async_reload_entry(hass, config_entry)


@pytest.mark.asyncio
async def test_setup_platforms(hass, config_entry):
    """Test setting up the sensor and calendar platforms."""
    config_entry.add_to_hass(hass)
    
    # Mock the forward_entry_setup calls
    with patch("homeassistant.config_entries.ConfigEntries.async_forward_entry_setup") as mock_setup:
        mock_setup.return_value = True
        
        assert await async_setup_entry(hass, config_entry)
        
        # Check that both platforms were set up
        assert mock_setup.call_count == 2
        platforms_setup = [args[0][1] for args in mock_setup.call_args_list]
        assert "sensor" in platforms_setup
        assert "calendar" in platforms_setup