"""Test UK Bin Collection options flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import data_entry_flow

from custom_components.uk_bin_collection.const import DOMAIN
from custom_components.uk_bin_collection.options_flow import (
    UkBinCollectionOptionsFlowHandler,
)

from .common_utils import MockConfigEntry


# Mock council data for options flow tests
MOCK_COUNCILS_DATA = {
    "CouncilTest": {
        "wiki_name": "Council Test",
        "uprn": True,
        "url": "https://example.com/council_test",
    }
}


@pytest.fixture
def config_entry(hass):
    """Create a mock config entry with hass object."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test Options",
            "council": "CouncilTest",
            "update_interval": 12,
            "icon_color_mapping": '{"General Waste": {"icon": "mdi:trash-can", "color": "brown"}}',
        },
        entry_id="options_test",
        unique_id="options_unique",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def options_flow(config_entry, hass):
    """Set up the options flow."""
    flow = UkBinCollectionOptionsFlowHandler(config_entry)
    flow.hass = hass
    
    # Mock get_councils_json method
    flow.get_councils_json = AsyncMock(return_value=MOCK_COUNCILS_DATA)
    
    return flow


@pytest.mark.asyncio
async def test_options_flow_init(options_flow):
    """Test the initial step of options flow."""
    result = await options_flow.async_step_init()
    
    # Should show form
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"
    assert "update_interval" in result["data_schema"].schema


@pytest.mark.asyncio
async def test_options_flow_update_interval(options_flow):
    """Test setting update_interval in options flow."""
    user_input = {
        "update_interval": 24,
    }
    
    with patch.object(options_flow.hass.config_entries, "async_update_entry"), \
         patch.object(options_flow.hass.config_entries, "async_reload"):
        result = await options_flow.async_step_init(user_input=user_input)
    
    # Should create entry
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["update_interval"] == 24
    # Original data should be preserved
    assert "icon_color_mapping" in result["data"]


@pytest.mark.asyncio
async def test_options_flow_invalid_update_interval(options_flow):
    """Test options flow with invalid update interval."""
    user_input = {
        "update_interval": 0,  # Invalid value
    }
    
    result = await options_flow.async_step_init(user_input=user_input)
    
    # Should show form with error
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"
    assert "update_interval" in result["errors"]


@pytest.mark.asyncio
async def test_options_flow_icon_color_mapping(options_flow):
    """Test setting icon_color_mapping in options flow."""
    new_mapping = '{"Recycling": {"icon": "mdi:recycle", "color": "green"}}'
    user_input = {
        "update_interval": 24,
        "icon_color_mapping": new_mapping,
    }
    
    with patch.object(options_flow.hass.config_entries, "async_update_entry"), \
         patch.object(options_flow.hass.config_entries, "async_reload"):
        result = await options_flow.async_step_init(user_input=user_input)
    
    # Should create entry with updated mapping
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["icon_color_mapping"] == new_mapping


@pytest.mark.asyncio
async def test_options_flow_invalid_json(options_flow):
    """Test options flow with invalid JSON in icon_color_mapping."""
    user_input = {
        "update_interval": 24,
        "icon_color_mapping": "invalid json",  # Invalid JSON
    }
    
    result = await options_flow.async_step_init(user_input=user_input)
    
    # Should show form with error
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"
    assert "icon_color_mapping" in result["errors"]


@pytest.mark.asyncio
async def test_options_flow_no_councils_data(hass, config_entry):
    """Test options flow when get_councils_json returns no data."""
    flow = UkBinCollectionOptionsFlowHandler(config_entry)
    flow.hass = hass
    
    # Mock get_councils_json to return empty data
    with patch.object(flow, "get_councils_json", AsyncMock(return_value={})):
        result = await flow.async_step_init()
    
    # Should abort with a reason
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert "reason" in result


@pytest.mark.asyncio
async def test_options_flow_manual_refresh_only(options_flow):
    """Test setting manual_refresh_only in options flow."""
    user_input = {
        "update_interval": 24,
        "manual_refresh_only": True,  # Enable manual refresh only
    }
    
    with patch.object(options_flow.hass.config_entries, "async_update_entry"), \
         patch.object(options_flow.hass.config_entries, "async_reload"):
        result = await options_flow.async_step_init(user_input=user_input)
    
    # Should create entry with manual_refresh_only enabled
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["manual_refresh_only"] is True