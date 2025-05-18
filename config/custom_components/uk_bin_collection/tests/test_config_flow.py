"""Test UkBinCollection config flow."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_NAME, CONF_URL
from homeassistant.core import HomeAssistant

from custom_components.uk_bin_collection.config_flow import UkBinCollectionConfigFlow
from custom_components.uk_bin_collection.const import DOMAIN

from .common_utils import MockConfigEntry


# Mock council data representing different scenarios
MOCK_COUNCILS_DATA = {
    "CouncilTest": {
        "wiki_name": "Council Test",
        "uprn": True,
        "url": "https://example.com/council_test",
        "skip_get_url": False,
    },
    "CouncilSkip": {
        "wiki_name": "Council Skip URL",
        "skip_get_url": True,
        "url": "https://example.com/skip",
    },
    "CouncilWithoutURL": {
        "wiki_name": "Council without URL",
        "skip_get_url": True,
        "uprn": True,
        "url": "https://example.com/council_without_url",
    },
    "CouncilWithUSRN": {
        "wiki_name": "Council with USRN",
        "usrn": True,
    },
    "CouncilWithUPRN": {
        "wiki_name": "Council with UPRN",
        "uprn": True,
    },
    "CouncilWithPostcodeNumber": {
        "wiki_name": "Council with Postcode and Number",
        "postcode": True,
        "house_number": True,
    },
    "CouncilWithWebDriver": {
        "wiki_name": "Council with Web Driver",
        "web_driver": True,
    },
}


# Helper function to initiate the config flow and proceed through steps
async def proceed_through_config_flow(
    hass: HomeAssistant, flow, user_input_initial, user_input_council
):
    """Helper to proceed through config flow steps."""
    # Start the flow and complete the `user` step
    result = await flow.async_step_user(user_input=user_input_initial)

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "council"

    # Complete the `council` step
    result = await flow.async_step_council(user_input=user_input_council)

    return result


@pytest.mark.asyncio
async def test_config_flow_with_uprn(hass):
    """Test config flow for a council requiring UPRN."""
    with patch(
        "custom_components.uk_bin_collection.config_flow.UkBinCollectionConfigFlow.get_councils_json",
        return_value=MOCK_COUNCILS_DATA,
    ):
        flow = UkBinCollectionConfigFlow()
        flow.hass = hass

        # Set up flow data
        user_input_initial = {
            "name": "Test Name",
            "council": "Council with UPRN",
        }
        user_input_council = {
            "uprn": "1234567890",
            "timeout": 60,
        }

        # Run the flow
        result = await proceed_through_config_flow(
            hass, flow, user_input_initial, user_input_council
        )

        # Check the result
        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "Test Name"
        assert result["data"] == {
            "name": "Test Name",
            "council": "CouncilWithUPRN",
            "uprn": "1234567890",
            "timeout": 60,
        }


@pytest.mark.asyncio
async def test_config_flow_with_postcode_and_number(hass):
    """Test config flow for a council requiring postcode and house number."""
    with patch(
        "custom_components.uk_bin_collection.config_flow.UkBinCollectionConfigFlow.get_councils_json",
        return_value=MOCK_COUNCILS_DATA,
    ):
        flow = UkBinCollectionConfigFlow()
        flow.hass = hass

        user_input_initial = {
            "name": "Test Name",
            "council": "Council with Postcode and Number",
        }
        user_input_council = {
            "postcode": "AB1 2CD",
            "number": "42",
            "timeout": 60,
        }

        result = await proceed_through_config_flow(
            hass, flow, user_input_initial, user_input_council
        )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "Test Name"
        assert result["data"] == {
            "name": "Test Name",
            "council": "CouncilWithPostcodeNumber",
            "postcode": "AB1 2CD",
            "number": "42",
            "timeout": 60,
        }


@pytest.mark.asyncio
async def test_config_flow_with_web_driver(hass):
    """Test config flow for a council requiring web driver."""
    with patch(
        "custom_components.uk_bin_collection.config_flow.UkBinCollectionConfigFlow.get_councils_json",
        return_value=MOCK_COUNCILS_DATA,
    ):
        flow = UkBinCollectionConfigFlow()
        flow.hass = hass

        user_input_initial = {
            "name": "Test Name",
            "council": "Council with Web Driver",
        }
        user_input_council = {
            "web_driver": "/path/to/webdriver",
            "headless": True,
            "local_browser": False,
            "timeout": 60,
        }

        result = await proceed_through_config_flow(
            hass, flow, user_input_initial, user_input_council
        )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "Test Name"
        assert result["data"] == {
            "name": "Test Name",
            "council": "CouncilWithWebDriver",
            "web_driver": "/path/to/webdriver",
            "headless": True,
            "local_browser": False,
            "timeout": 60,
        }


@pytest.mark.asyncio
async def test_config_flow_skipping_url(hass):
    """Test config flow for a council that skips URL input."""
    with patch(
        "custom_components.uk_bin_collection.config_flow.UkBinCollectionConfigFlow.get_councils_json",
        return_value=MOCK_COUNCILS_DATA,
    ):
        flow = UkBinCollectionConfigFlow()
        flow.hass = hass

        user_input_initial = {
            "name": "Test Name",
            "council": "Council Skip URL",
        }
        user_input_council = {
            "timeout": 60,
        }

        result = await proceed_through_config_flow(
            hass, flow, user_input_initial, user_input_council
        )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "Test Name"
        assert result["data"] == {
            "name": "Test Name",
            "council": "CouncilSkip",
            "skip_get_url": True,
            "url": "https://example.com/skip",
            "timeout": 60,
        }


@pytest.mark.asyncio
async def test_config_flow_missing_name(hass):
    """Test config flow when name is missing."""
    with patch(
        "custom_components.uk_bin_collection.config_flow.UkBinCollectionConfigFlow.get_councils_json",
        return_value=MOCK_COUNCILS_DATA,
    ):
        flow = UkBinCollectionConfigFlow()
        flow.hass = hass

        user_input_initial = {
            "name": "",  # Missing name
            "council": "Council with UPRN",
        }

        result = await flow.async_step_user(user_input=user_input_initial)

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"
        assert "name" in result["errors"]


@pytest.mark.asyncio
async def test_config_flow_with_usrn(hass):
    """Test config flow for a council requiring USRN."""
    with patch(
        "custom_components.uk_bin_collection.config_flow.UkBinCollectionConfigFlow.get_councils_json",
        return_value=MOCK_COUNCILS_DATA,
    ):
        flow = UkBinCollectionConfigFlow()
        flow.hass = hass

        user_input_initial = {
            "name": "Test Name",
            "council": "Council with USRN",
        }
        user_input_council = {
            "usrn": "9876543210",
            "timeout": 60,
        }

        result = await proceed_through_config_flow(
            hass, flow, user_input_initial, user_input_council
        )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "Test Name"
        assert result["data"] == {
            "name": "Test Name",
            "council": "CouncilWithUSRN",
            "usrn": "9876543210",
            "timeout": 60,
        }


@pytest.mark.asyncio
async def test_get_councils_json_failure(hass):
    """Test handling when get_councils_json fails."""
    with patch(
        "aiohttp.ClientSession.get",
        side_effect=Exception("Network error"),
    ):
        flow = UkBinCollectionConfigFlow()
        flow.hass = hass
        
        result = await flow.get_councils_json()
        assert result == {}


@pytest.mark.asyncio
async def test_config_flow_user_input_none(hass):
    """Test config flow when user_input is None."""
    with patch(
        "custom_components.uk_bin_collection.config_flow.UkBinCollectionConfigFlow.get_councils_json",
        return_value=MOCK_COUNCILS_DATA,
    ):
        flow = UkBinCollectionConfigFlow()
        flow.hass = hass

        result = await flow.async_step_user(user_input=None)

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_config_flow_missing_council(hass):
    """Test config flow when council is missing."""
    with patch(
        "custom_components.uk_bin_collection.config_flow.UkBinCollectionConfigFlow.get_councils_json",
        return_value=MOCK_COUNCILS_DATA,
    ):
        flow = UkBinCollectionConfigFlow()
        flow.hass = hass

        user_input_initial = {
            "name": "Test Name",
            "council": "",  # Missing council
        }

        result = await flow.async_step_user(user_input=user_input_initial)

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"
        assert "council" in result["errors"]