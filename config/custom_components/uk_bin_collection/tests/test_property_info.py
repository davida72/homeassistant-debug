"""Test UK Bin Collection property info module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp

from custom_components.uk_bin_collection.property_info import (
    PropertyInfo,
    PropertyLookupError,
    get_property_info,
)


@pytest.fixture
def mock_property_response():
    """Return a mock property response."""
    return {
        "results": [
            {
                "uprn": "1234567890",
                "address": "1 Test Street, Testville",
                "postcode": "TE1 1ST"
            }
        ]
    }


@pytest.fixture
def mock_empty_response():
    """Return a mock empty response."""
    return {"results": []}


@pytest.mark.asyncio
async def test_get_property_info_success(mock_property_response):
    """Test successful property lookup."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_property_response)
        mock_get.return_value.__aenter__.return_value = mock_response
        
        result = await get_property_info("TE1 1ST", "1")
        
        assert result == mock_property_response["results"][0]
        assert "uprn" in result
        assert result["uprn"] == "1234567890"


@pytest.mark.asyncio
async def test_get_property_info_no_results(mock_empty_response):
    """Test property lookup with no results."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_empty_response)
        mock_get.return_value.__aenter__.return_value = mock_response
        
        with pytest.raises(PropertyLookupError, match="No properties found"):
            await get_property_info("ZZ9 9ZZ", "999")


@pytest.mark.asyncio
async def test_get_property_info_http_error():
    """Test property lookup with HTTP error."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status = 404
        mock_get.return_value.__aenter__.return_value = mock_response
        
        with pytest.raises(PropertyLookupError, match="HTTP error 404"):
            await get_property_info("TE1 1ST", "1")


@pytest.mark.asyncio
async def test_get_property_info_connection_error():
    """Test property lookup with connection error."""
    with patch("aiohttp.ClientSession.get", side_effect=aiohttp.ClientError("Connection error")):
        with pytest.raises(PropertyLookupError):
            await get_property_info("TE1 1ST", "1")


def test_property_info_class():
    """Test PropertyInfo class."""
    # Test initialization
    prop_info = PropertyInfo("1234567890", "1 Test Street", "TE1 1ST")
    
    assert prop_info.uprn == "1234567890"
    assert prop_info.address == "1 Test Street"
    assert prop_info.postcode == "TE1 1ST"
    
    # Test string representation
    assert str(prop_info) == "1 Test Street, TE1 1ST (UPRN: 1234567890)"
    
    # Test from_dict method
    data = {
        "uprn": "9876543210",
        "address": "2 Another Road",
        "postcode": "AB1 2CD"
    }
    
    prop_info2 = PropertyInfo.from_dict(data)
    assert prop_info2.uprn == "9876543210"
    assert prop_info2.address == "2 Another Road"
    assert prop_info2.postcode == "AB1 2CD"


@pytest.mark.asyncio
async def test_get_property_info_invalid_json():
    """Test property lookup with invalid JSON response."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(side_effect=ValueError("Invalid JSON"))
        mock_get.return_value.__aenter__.return_value = mock_response
        
        with pytest.raises(PropertyLookupError, match="Failed to parse"):
            await get_property_info("TE1 1ST", "1")


def test_property_info_missing_fields():
    """Test PropertyInfo with missing fields."""
    # Test partial data
    partial_data = {
        "uprn": "1234567890",
        # Missing address and postcode
    }
    
    prop_info = PropertyInfo.from_dict(partial_data)
    assert prop_info.uprn == "1234567890"
    assert prop_info.address == ""  # Should default to empty string
    assert prop_info.postcode == ""  # Should default to empty string


def test_property_info_equality():
    """Test PropertyInfo equality comparison."""
    prop1 = PropertyInfo("1234567890", "Test Address", "TE1 1ST")
    prop2 = PropertyInfo("1234567890", "Test Address", "TE1 1ST")
    prop3 = PropertyInfo("9876543210", "Other Address", "OT1 1ST")
    
    # Same data should be equal
    assert prop1 == prop2
    
    # Different data should not be equal
    assert prop1 != prop3
    
    # Different type should not be equal
    assert prop1 != "not a PropertyInfo object"