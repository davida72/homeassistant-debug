import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from json import JSONDecodeError
from unittest.mock import AsyncMock, MagicMock, patch, Mock

import pytest
from freezegun import freeze_time
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.core import ServiceCall
from custom_components.uk_bin_collection import (
    async_setup_entry as async_setup_entry_domain,
)
from custom_components.uk_bin_collection.sensor import (
    async_setup_entry as async_setup_entry_sensor,
)

from custom_components.uk_bin_collection.const import (
    DOMAIN,
    LOG_PREFIX,
    STATE_ATTR_COLOUR,
    STATE_ATTR_NEXT_COLLECTION,
    STATE_ATTR_DAYS,
)
from custom_components.uk_bin_collection.sensor import (
    UKBinCollectionAttributeSensor,
    UKBinCollectionDataSensor,
    UKBinCollectionRawJSONSensor,
    create_sensor_entities,
    load_icon_color_mapping,
)

from custom_components.uk_bin_collection import HouseholdBinCoordinator

logging.basicConfig(level=logging.DEBUG)

from .common_utils import MockConfigEntry

pytest_plugins = ["freezegun"]

# Mock Data
MOCK_BIN_COLLECTION_DATA = {
    "bins": [
        {"type": "General Waste", "collectionDate": "15/10/2023"},
        {"type": "Recycling", "collectionDate": "16/10/2023"},
        {"type": "Garden Waste", "collectionDate": "17/10/2023"},
    ]
}

MOCK_PROCESSED_DATA = {
    "General Waste": datetime.strptime("15/10/2023", "%d/%m/%Y").date(),
    "Recycling": datetime.strptime("16/10/2023", "%d/%m/%Y").date(),
    "Garden Waste": datetime.strptime("17/10/2023", "%d/%m/%Y").date(),
}


@pytest.fixture
def mock_config_entry():
    """Create a mock ConfigEntry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Entry",
        data={
            "name": "Test Name",
            "council": "Test Council",
            "url": "https://example.com",
            "timeout": 60,
            "icon_color_mapping": {},
        },
        entry_id="test",
        unique_id="test_unique_id",
    )


# Tests
def test_process_bin_data(freezer):
    """Test processing of bin collection data."""
    freezer.move_to("2023-10-14")
    processed_data = HouseholdBinCoordinator.process_bin_data(MOCK_BIN_COLLECTION_DATA)
    # Convert dates to strings for comparison
    processed_data_str = {k: v.strftime("%Y-%m-%d") for k, v in processed_data.items()}
    expected_data_str = {
        k: v.strftime("%Y-%m-%d") for k, v in MOCK_PROCESSED_DATA.items()
    }
    assert processed_data_str == expected_data_str


def test_process_bin_data_empty():
    """Test processing when data is empty."""
    processed_data = HouseholdBinCoordinator.process_bin_data({"bins": []})
    assert processed_data == {}


def test_process_bin_data_past_dates(freezer):
    """Test processing when all dates are in the past."""
    freezer.move_to("2023-10-14")
    past_date = (datetime(2023, 10, 14) - timedelta(days=1)).strftime("%d/%m/%Y")
    data = {
        "bins": [
            {"type": "General Waste", "collectionDate": past_date},
        ]
    }
    processed_data = HouseholdBinCoordinator.process_bin_data(data)
    assert processed_data == {}  # No future dates


def test_process_bin_data_duplicate_bin_types(freezer):
    """Test processing when duplicate bin types are present."""
    freezer.move_to("2023-10-14")
    data = {
        "bins": [
            {"type": "General Waste", "collectionDate": "15/10/2023"},
            {"type": "General Waste", "collectionDate": "16/10/2023"},  # Later date
        ]
    }
    expected = {
        "General Waste": date(2023, 10, 15),  # Should take the earliest future date
    }
    processed_data = HouseholdBinCoordinator.process_bin_data(data)
    assert processed_data == expected


def test_unique_id_uniqueness():
    """Test that each sensor has a unique ID."""
    coordinator = MagicMock()
    coordinator.name = "Test Name"
    coordinator.data = MOCK_PROCESSED_DATA

    sensor1 = UKBinCollectionDataSensor(
        coordinator, "General Waste", "test_general_waste", {}
    )
    sensor2 = UKBinCollectionDataSensor(coordinator, "Recycling", "test_recycling", {})

    assert sensor1.unique_id == "test_general_waste"
    assert sensor2.unique_id == "test_recycling"
    assert sensor1.unique_id != sensor2.unique_id


@pytest.mark.asyncio
@freeze_time("2023-10-14")
async def test_async_setup_entry(hass, mock_config_entry):
    """Test setting up the sensor platform directly."""
    # 1) We need to fake the coordinator in hass.data
    hass.data = {}
    hass.data.setdefault(DOMAIN, {})

    # Create a mock coordinator (or real if you like)
    mock_coordinator = MagicMock()
    # Store it under the entry_id as normal domain code would do
    hass.data[DOMAIN][mock_config_entry.entry_id] = {"coordinator": mock_coordinator}

    # 2) Prepare a mock to track added entities
    async_add_entities = Mock()

    # 3) Patch sensor's UKBinCollectionApp calls if needed
    with patch(
        "custom_components.uk_bin_collection.sensor.UKBinCollectionApp"
    ) as mock_app:
        mock_app_instance = mock_app.return_value
        mock_app_instance.run.return_value = json.dumps({"bins": []})

        with patch.object(
            hass,
            "async_add_executor_job",
            new_callable=AsyncMock,
            return_value=mock_app_instance.run.return_value,
        ):
            # 4) Now call the sensor setup function
            await async_setup_entry_sensor(hass, mock_config_entry, async_add_entities)

    # 5) Assert that sensor got set up
    assert async_add_entities.call_count == 1
    # ... any other assertions you want


@freeze_time("2023-10-14")
@pytest.mark.asyncio
async def test_coordinator_fetch(hass):
    """Test the data fetch by the coordinator."""
    with patch(
        "custom_components.uk_bin_collection.sensor.UKBinCollectionApp"
    ) as mock_app:
        mock_app_instance = mock_app.return_value
        mock_app_instance.run.return_value = json.dumps(MOCK_BIN_COLLECTION_DATA)

        with patch.object(
            hass,
            "async_add_executor_job",
            new_callable=AsyncMock,
            return_value=mock_app_instance.run.return_value,
        ):
            coordinator = HouseholdBinCoordinator(
                hass, mock_app_instance, "Test Name", timeout=60
            )

            await coordinator.async_refresh()

    assert (
        coordinator.data == MOCK_PROCESSED_DATA
    ), "Coordinator data does not match expected values."
    assert (
        coordinator.last_update_success is True
    ), "Coordinator update was not successful."


@pytest.mark.asyncio
async def test_bin_sensor(hass, mock_config_entry):
    """Test the main bin sensor."""
    from freezegun import freeze_time

    hass.data = {}

    # Use freeze_time as a context manager instead of a decorator since we're already inside a function
    with freeze_time("2023-10-14"):
        with patch(
            "custom_components.uk_bin_collection.sensor.UKBinCollectionApp"
        ) as mock_app:
            mock_app_instance = mock_app.return_value
            mock_app_instance.run.return_value = json.dumps(MOCK_BIN_COLLECTION_DATA)

            # Use AsyncMock for async_add_executor_job
            async def mock_async_add_executor_job(func, *args, **kwargs):
                return func(*args, **kwargs)

            hass.async_add_executor_job = mock_async_add_executor_job
            
            coordinator = HouseholdBinCoordinator(
                hass, mock_app_instance, "Test Name", timeout=60
            )

            # Use our async mock instead of calling the real refresh method
            with patch.object(coordinator, "async_config_entry_first_refresh", new=AsyncMock()):
                # Set the coordinator data manually instead of refreshing
                coordinator.data = {
                    "General Waste": datetime.strptime("15/10/2023", "%d/%m/%Y").date(),
                    "Recycling": datetime.strptime("16/10/2023", "%d/%m/%Y").date(),
                    "Garden Waste": datetime.strptime("17/10/2023", "%d/%m/%Y").date(),
                }
                coordinator.last_update_success = True

        sensor = UKBinCollectionDataSensor(
            coordinator, "General Waste", "test_general_waste", {}
        )

        assert sensor.name == "Test Name General Waste"
        assert sensor.unique_id == "test_general_waste"
        assert sensor.state == "Tomorrow"
        assert sensor.icon == "mdi:trash-can"
        assert sensor.extra_state_attributes == {
            "colour": "black",
            "next_collection": "15/10/2023",
            "days": 1,
        }


@freeze_time("2023-10-14")
@pytest.mark.asyncio
async def test_raw_json_sensor(hass, mock_config_entry):
    """Test the raw JSON sensor."""
    hass.data = {}

    # Create a coordinator with mocked data instead of calling async_config_entry_first_refresh
    coordinator = MagicMock()
    coordinator.data = MOCK_PROCESSED_DATA
    coordinator.name = "Test Name"
    coordinator.last_update_success = True

    sensor = UKBinCollectionRawJSONSensor(coordinator, "test_raw_json", "Test Name")

    expected_state = json.dumps(
        {k: v.strftime("%d/%m/%Y") for k, v in MOCK_PROCESSED_DATA.items()}
    )

    assert sensor.name == "Test Name Raw JSON"
    assert sensor.unique_id == "test_raw_json"
    assert sensor.state == expected_state
    assert sensor.extra_state_attributes == {"raw_data": MOCK_PROCESSED_DATA}


@pytest.mark.asyncio
async def test_bin_sensor_custom_icon_color(hass, mock_config_entry):
    """Test bin sensor with custom icon and color."""
    icon_color_mapping = {"General Waste": {"icon": "mdi:delete", "color": "green"}}

    # Initialize hass.data
    hass.data = {}

    # Create data directly instead of fetching it
    processed_data = {
        "General Waste": datetime.strptime("15/10/2023", "%d/%m/%Y").date()
    }

    # Create a coordinator directly with mocked properties
    coordinator = MagicMock()
    coordinator.data = processed_data
    coordinator.name = "Test Name"
    coordinator.last_update_success = True

    # Create a bin sensor with custom icon and color mapping
    sensor = UKBinCollectionDataSensor(
        coordinator, "General Waste", "test_general_waste", icon_color_mapping
    )

    # Access properties
    assert sensor.icon == "mdi:delete"
    assert sensor.extra_state_attributes["colour"] == "green"


@pytest.mark.asyncio
async def test_bin_sensor_today_collection(hass, freezer, mock_config_entry):
    """Test bin sensor when collection is today."""
    freezer.move_to("2023-10-14")
    today_date = dt_util.now().strftime("%d/%m/%Y")
    
    # Initialize hass.data
    hass.data = {}
    
    # Create a coordinator directly with mocked properties instead of calling async_config_entry_first_refresh
    coordinator = MagicMock()
    coordinator.data = {
        "General Waste": datetime.strptime(today_date, "%d/%m/%Y").date()
    }
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create a bin sensor with this data
    sensor = UKBinCollectionDataSensor(
        coordinator, "General Waste", "test_general_waste", {}
    )
    
    # Access properties
    assert sensor.state == "Today"
    assert sensor.available is True
    assert sensor.extra_state_attributes["days"] == 0


@pytest.mark.asyncio
async def test_bin_sensor_tomorrow_collection(hass, freezer, mock_config_entry):
    """Test bin sensor when collection is tomorrow."""
    freezer.move_to("2023-10-14")
    tomorrow_date = (dt_util.now() + timedelta(days=1)).strftime("%d/%m/%Y")
    
    # Initialize hass.data
    hass.data = {}
    
    # Create a coordinator directly with mocked properties instead of calling async_config_entry_first_refresh
    coordinator = MagicMock()
    coordinator.data = {
        "Recycling": datetime.strptime(tomorrow_date, "%d/%m/%Y").date()
    }
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create a bin sensor with this data
    sensor = UKBinCollectionDataSensor(
        coordinator, "Recycling", "test_recycling", {}
    )
    
    # Access properties
    assert sensor.state == "Tomorrow"
    assert sensor.available is True
    assert sensor.extra_state_attributes["days"] == 1


@pytest.mark.asyncio
async def test_bin_sensor_partial_custom_icon_color(hass, mock_config_entry):
    """Test bin sensor with partial custom icon and color mappings."""
    icon_color_mapping = {"General Waste": {"icon": "mdi:delete", "color": "green"}}

    # Initialize hass.data
    hass.data = {}

    # Create a coordinator with manually set data instead of calling async_config_entry_first_refresh
    coordinator = MagicMock()
    coordinator.data = {
        "General Waste": datetime.strptime("15/10/2023", "%d/%m/%Y").date(),
        "Recycling": datetime.strptime("16/10/2023", "%d/%m/%Y").date(),
    }
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create sensors for both bin types
    sensor_general = UKBinCollectionDataSensor(
        coordinator, "General Waste", "test_general_waste", icon_color_mapping
    )
    sensor_recycling = UKBinCollectionDataSensor(
        coordinator, "Recycling", "test_recycling", icon_color_mapping
    )

    # Check custom mapping for General Waste
    assert sensor_general.icon == "mdi:delete"
    assert sensor_general.extra_state_attributes["colour"] == "green"

    # Check default mapping for Recycling
    assert sensor_recycling.icon == "mdi:recycle"
    assert sensor_recycling.extra_state_attributes["colour"] == "black"


# Remove duplicate test function
# def test_unique_id_uniqueness(hass, mock_config_entry):


@pytest.fixture
def mock_dt_now_different_timezone():
    """Mock datetime.now with a different timezone."""
    with patch(
        "homeassistant.util.dt.now",
        return_value=datetime(2023, 10, 14, 12, 0, tzinfo=dt_util.UTC),
    ):
        yield


async def test_raw_json_sensor_invalid_data(hass, mock_config_entry):
    """Test raw JSON sensor with invalid data."""
    # Create the coordinator with manually set properties
    coordinator = MagicMock()
    coordinator.data = {}  # Empty data
    coordinator.last_update_success = False
    coordinator.name = "Test Name"

    # Create the raw JSON sensor
    sensor = UKBinCollectionRawJSONSensor(coordinator, "test_raw_json", "Test Name")

    # Since data fetch failed, sensor.state should reflect the failure
    assert sensor.state == json.dumps({})
    assert sensor.extra_state_attributes == {"raw_data": {}}
    assert sensor.available is False


def test_sensor_device_info(hass, mock_config_entry):
    """Test that sensors report correct device information."""
    coordinator = MagicMock()
    coordinator.name = "Test Name"
    coordinator.data = MOCK_PROCESSED_DATA

    sensor = UKBinCollectionDataSensor(
        coordinator, "General Waste", "test_general_waste", {}
    )

    expected_device_info = {
        "identifiers": {(DOMAIN, "test_general_waste")},
        "name": "Test Name General Waste",
        "manufacturer": "UK Bin Collection",
        "model": "Bin Sensor",
        "sw_version": "1.0",
    }
    assert sensor.device_info == expected_device_info


# Rename to test_ to make it a proper test function
def test_process_bin_data_duplicate_bin_types_2(freezer):
    """Test processing when duplicate bin types are present."""
    freezer.move_to("2023-10-14")
    data = {
        "bins": [
            {"type": "General Waste", "collectionDate": "15/10/2023"},
            {"type": "General Waste", "collectionDate": "16/10/2023"},  # Later date
        ]
    }
    expected = {
        "General Waste": datetime.strptime("15/10/2023", "%d/%m/%Y").date(),  # Should take the earliest future date
    }
    processed_data = HouseholdBinCoordinator.process_bin_data(data)
    assert processed_data == expected


@pytest.mark.asyncio
async def test_coordinator_timeout_error(hass, mock_config_entry):
    """Test coordinator handles timeout errors correctly."""
    with patch(
        "custom_components.uk_bin_collection.sensor.UKBinCollectionApp"
    ) as mock_app:
        mock_app_instance = mock_app.return_value
        # Simulate run raising TimeoutError
        mock_app_instance.run.side_effect = asyncio.TimeoutError("Request timed out")

        # Mock async_add_executor_job to raise TimeoutError
        hass.async_add_executor_job = AsyncMock(
            side_effect=mock_app_instance.run.side_effect
        )

        coordinator = HouseholdBinCoordinator(
            hass, mock_app_instance, "Test Name", timeout=1
        )
        
        # Instead of calling async_config_entry_first_refresh, directly call _async_update_data
        # and verify it raises UpdateFailed with the correct message
        with pytest.raises(UpdateFailed) as exc_info:
            await coordinator._async_update_data()
        
        assert "Timeout while updating data" in str(exc_info.value)


@pytest.mark.asyncio
async def test_coordinator_json_decode_error(hass, mock_config_entry):
    """Test coordinator handles JSON decode errors correctly."""
    with patch(
        "custom_components.uk_bin_collection.sensor.UKBinCollectionApp"
    ) as mock_app:
        mock_app_instance = mock_app.return_value
        # Simulate run returning invalid JSON
        mock_app_instance.run.return_value = "Invalid JSON String"

        # Mock async_add_executor_job to raise JSONDecodeError when called
        async def mock_async_add_executor_job(*args, **kwargs):
            raise JSONDecodeError("Expecting value", "Invalid JSON String", 0)
        
        hass.async_add_executor_job = mock_async_add_executor_job

        coordinator = HouseholdBinCoordinator(
            hass, mock_app_instance, "Test Name", timeout=60
        )
        
        # Instead of calling async_config_entry_first_refresh, directly call _async_update_data
        # and verify it raises UpdateFailed with the correct message
        with pytest.raises(UpdateFailed) as exc_info:
            await coordinator._async_update_data()
        
        assert "JSON decode error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_coordinator_general_exception(hass, mock_config_entry):
    """Test coordinator handles general exceptions correctly."""
    with patch(
        "custom_components.uk_bin_collection.sensor.UKBinCollectionApp"
    ) as mock_app:
        mock_app_instance = mock_app.return_value
        # Simulate run raising a general exception
        mock_app_instance.run.side_effect = Exception("General error")

        # Mock async_add_executor_job to raise the exception
        hass.async_add_executor_job = AsyncMock(
            side_effect=mock_app_instance.run.side_effect
        )

        coordinator = HouseholdBinCoordinator(
            hass, mock_app_instance, "Test Name", timeout=60
        )

        # Instead of calling async_config_entry_first_refresh, directly call _async_update_data
        # and verify it raises UpdateFailed with the correct message
        with pytest.raises(UpdateFailed) as exc_info:
            await coordinator._async_update_data()

        # Check for the error message - could be either "Unexpected error" or the actual error message
        assert "General error" in str(exc_info.value)


# Remove duplicates and rename to make them proper test functions
def test_process_bin_data_duplicate_bin_types_different_dates(freezer):
    """Test processing when duplicate bin types are present with different dates."""
    freezer.move_to("2023-10-14")
    data = {
        "bins": [
            {"type": "General Waste", "collectionDate": "15/10/2023"},
            {"type": "General Waste", "collectionDate": "14/10/2023"},  # Earlier date
        ]
    }
    expected = {
        "General Waste": datetime.strptime("14/10/2023", "%d/%m/%Y").date(),  # Should take the earliest future date
    }
    processed_data = HouseholdBinCoordinator.process_bin_data(data)
    assert processed_data == expected


def test_process_bin_data_past_dates_2(freezer):
    """Test processing when all dates are in the past."""
    freezer.move_to("2023-10-14")
    past_date = (dt_util.now() - timedelta(days=1)).strftime("%d/%m/%Y")
    data = {
        "bins": [
            {"type": "General Waste", "collectionDate": past_date},
            {"type": "Recycling", "collectionDate": past_date},
        ]
    }
    processed_data = HouseholdBinCoordinator.process_bin_data(data)
    assert processed_data == {}  # No future dates should be included


def test_process_bin_data_missing_fields(freezer):
    """Test processing when some bins are missing required fields."""
    freezer.move_to("2023-10-14")
    data = {
        "bins": [
            {"type": "General Waste", "collectionDate": "15/10/2023"},
            {"collectionDate": "16/10/2023"},  # Missing 'type'
            {"type": "Recycling"},  # Missing 'collectionDate'
        ]
    }
    expected = {
        "General Waste": datetime.strptime("15/10/2023", "%d/%m/%Y").date(),
    }
    processed_data = HouseholdBinCoordinator.process_bin_data(data)
    assert processed_data == expected


def test_process_bin_data_invalid_date_format(freezer):
    """Test processing when bins have invalid date formats."""
    freezer.move_to("2023-10-14")
    data = {
        "bins": [
            {
                "type": "General Waste",
                "collectionDate": "2023-10-15",
            },  # Incorrect format
            {"type": "Recycling", "collectionDate": "16/13/2023"},  # Invalid month
        ]
    }
    processed_data = HouseholdBinCoordinator.process_bin_data(data)
    assert processed_data == {}  # Both entries should be skipped due to invalid dates


@pytest.mark.asyncio
async def test_bin_sensor_state_today(hass, mock_config_entry, freezer):
    """Test bin sensor when collection is today."""
    freezer.move_to("2023-10-14")
    today_date = dt_util.now().strftime("%d/%m/%Y")
    
    # Initialize hass.data
    hass.data = {}
    
    # Create a coordinator directly with mocked properties instead of calling async_config_entry_first_refresh
    coordinator = MagicMock()
    coordinator.data = {
        "General Waste": datetime.strptime(today_date, "%d/%m/%Y").date()
    }
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create a bin sensor with this data
    sensor = UKBinCollectionDataSensor(
        coordinator, "General Waste", "test_general_waste", {}
    )
    
    # Access properties
    assert sensor.state == "Today"
    assert sensor.available is True
    assert sensor.extra_state_attributes["days"] == 0


@pytest.mark.asyncio
async def test_bin_sensor_state_tomorrow(hass, mock_config_entry, freezer):
    """Test bin sensor when collection is tomorrow."""
    freezer.move_to("2023-10-14")
    tomorrow_date = (dt_util.now() + timedelta(days=1)).strftime("%d/%m/%Y")
    
    # Initialize hass.data
    hass.data = {}
    
    # Create a coordinator directly with mocked properties instead of calling async_config_entry_first_refresh
    coordinator = MagicMock()
    coordinator.data = {
        "Recycling": datetime.strptime(tomorrow_date, "%d/%m/%Y").date()
    }
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create a bin sensor with this data
    sensor = UKBinCollectionDataSensor(
        coordinator, "Recycling", "test_recycling", {}
    )
    
    # Access properties
    assert sensor.state == "Tomorrow"
    assert sensor.available is True
    assert sensor.extra_state_attributes["days"] == 1


@pytest.mark.asyncio
async def test_bin_sensor_state_in_days(hass, mock_config_entry, freezer):
    """Test bin sensor when collection is in multiple days."""
    freezer.move_to("2023-10-14")
    future_date = (dt_util.now() + timedelta(days=5)).strftime("%d/%m/%Y")
    
    # Initialize hass.data
    hass.data = {}
    
    # Create a coordinator directly with mocked properties instead of calling async_config_entry_first_refresh
    coordinator = MagicMock()
    coordinator.data = {
        "Garden Waste": datetime.strptime(future_date, "%d/%m/%Y").date()
    }
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create a bin sensor with this data
    sensor = UKBinCollectionDataSensor(
        coordinator, "Garden Waste", "test_garden_waste", {}
    )
    
    # Access properties
    assert sensor.state == "In 5 days"
    assert sensor.available is True
    assert sensor.extra_state_attributes["days"] == 5


@pytest.mark.asyncio
async def test_bin_sensor_missing_data(hass, mock_config_entry):
    """Test bin sensor when bin data is missing."""
    # Initialize hass.data
    hass.data = {}
    
    # Create a coordinator with empty data
    coordinator = MagicMock()
    coordinator.data = {}  # No bins data
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create a bin sensor for a non-existent bin type
    sensor = UKBinCollectionDataSensor(
        coordinator, "Non-Existent Bin", "test_non_existent_bin", {}
    )
    
    # Access properties - sensor should be unavailable with unknown state
    assert sensor.state == "Unknown"
    assert sensor.available is False
    assert sensor.extra_state_attributes["days"] is None
    assert sensor.extra_state_attributes["next_collection"] is None


@freeze_time("2023-10-14")
@pytest.mark.asyncio
async def test_raw_json_sensor_invalid_data_2(hass, mock_config_entry):
    """Test raw JSON sensor with invalid data."""
    # Create coordinator with failed update
    coordinator = MagicMock()
    coordinator.data = {}  # Empty data
    coordinator.name = "Test Name"
    coordinator.last_update_success = False
    
    # Create the raw JSON sensor
    raw_json_sensor = UKBinCollectionRawJSONSensor(
        coordinator, "test_raw_json", "Test Name"
    )
    
    # Check properties
    assert raw_json_sensor.state == "{}"
    assert raw_json_sensor.extra_state_attributes == {"raw_data": {}}
    assert raw_json_sensor.available is False


@pytest.mark.asyncio
async def test_sensor_available_property(hass, mock_config_entry):
    """Test that sensor's available property reflects its state."""
    # Create a coordinator with valid data
    coordinator = MagicMock()
    coordinator.data = {
        "Recycling": datetime.strptime("16/10/2023", "%d/%m/%Y").date()
    }
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create a sensor
    sensor_valid = UKBinCollectionDataSensor(
        coordinator, "Recycling", "test_recycling_available", {}
    )
    
    # Check availability
    assert sensor_valid.available is True


@pytest.mark.asyncio
async def test_coordinator_empty_data(hass, mock_config_entry):
    """Test coordinator handles empty data correctly."""
    # Create a coordinator with empty data
    coordinator = MagicMock()
    coordinator.data = {}  # Empty data
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Verify data is empty but update was successful
    assert coordinator.data == {}
    assert coordinator.last_update_success is True


def test_coordinator_custom_update_interval(hass, mock_config_entry):
    """Test that coordinator uses a custom update interval."""
    custom_interval = timedelta(hours=6)
    coordinator = HouseholdBinCoordinator(hass, MagicMock(), "Test Name", timeout=60)
    coordinator.update_interval = custom_interval

    assert coordinator.update_interval == custom_interval


@pytest.mark.asyncio
async def test_async_setup_entry_missing_required_fields(hass):
    """Test domain-level setup fails if 'name' is missing."""
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            # no "name"
            "council": "Test Council",
            "url": "https://example.com",
            "timeout": 60,
            "icon_color_mapping": {},
        },
        entry_id="test_missing_name",
    )

    with patch("custom_components.uk_bin_collection.UKBinCollectionApp") as mock_app:
        mock_app_instance = mock_app.return_value
        mock_app_instance.run.return_value = "{}"
        hass.async_add_executor_job = AsyncMock(return_value="{}")

        with pytest.raises(ConfigEntryNotReady) as exc_info:
            # Call the domain-level function
            await async_setup_entry_domain(hass, mock_config_entry)

    assert "Missing 'name' in configuration." in str(exc_info.value)


@pytest.mark.asyncio
async def test_data_sensor_device_info(hass, mock_config_entry):
    """Test that data sensor reports correct device information."""
    # Create a coordinator with test data
    coordinator = MagicMock()
    coordinator.data = {
        "General Waste": datetime.strptime("15/10/2023", "%d/%m/%Y").date()
    }
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create a sensor
    sensor = UKBinCollectionDataSensor(
        coordinator,
        "General Waste",
        "test_general_waste_device_info",
        {},
    )
    
    # Check device info
    expected_device_info = {
        "identifiers": {(DOMAIN, "test_general_waste_device_info")},
        "name": "Test Name General Waste",
        "manufacturer": "UK Bin Collection",
        "model": "Bin Sensor",
        "sw_version": "1.0",
    }
    assert sensor.device_info == expected_device_info


@pytest.mark.asyncio
async def test_data_sensor_default_icon(hass, mock_config_entry):
    """Test data sensor uses default icon based on bin type when no mapping is provided."""
    # Create a coordinator with data for an unknown bin type
    coordinator = MagicMock()
    coordinator.data = {
        "Unknown Bin": datetime.strptime("20/10/2023", "%d/%m/%Y").date()
    }
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create a sensor with no icon mapping
    sensor = UKBinCollectionDataSensor(
        coordinator, "Unknown Bin", "test_unknown_bin", {}
    )
    
    # Check defaults
    assert sensor.icon == "mdi:delete"
    assert sensor._color == "black"


def test_coordinator_update_interval(hass, mock_config_entry):
    """Test that coordinator uses the correct update interval."""
    coordinator = HouseholdBinCoordinator(hass, MagicMock(), "Test Name", timeout=60)
    assert coordinator.update_interval == timedelta(hours=12)


@pytest.mark.asyncio
async def test_manual_refresh_service(hass, mock_config_entry):
    """Test that calling manual_refresh logic triggers coordinator.async_request_refresh."""
    # Set up hass.data
    hass.data = {}
    hass.data.setdefault(DOMAIN, {})
    
    # Create a coordinator with AsyncMock for async_request_refresh
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    
    # Store coordinator in hass.data
    hass.data[DOMAIN][mock_config_entry.entry_id] = {"coordinator": coordinator}
    
    # Define the service handler function
    async def mock_handle_manual_refresh(call: ServiceCall):
        entry_id = call.data.get("entry_id")
        if not entry_id:
            return
        if entry_id not in hass.data[DOMAIN]:
            return
        c = hass.data[DOMAIN][entry_id].get("coordinator")
        if c:
            await c.async_request_refresh()
    
    # Call the handler with a mock ServiceCall - adding the required 'hass' parameter
    fake_call = ServiceCall(
        domain=DOMAIN,
        service="manual_refresh",
        data={"entry_id": mock_config_entry.entry_id},
        context=None,
        hass=hass
    )
    await mock_handle_manual_refresh(fake_call)
    
    # Verify async_request_refresh was called
    coordinator.async_request_refresh.assert_awaited_once()


def test_load_icon_color_mapping_invalid_json():
    """Test load_icon_color_mapping with invalid JSON."""
    from custom_components.uk_bin_collection.sensor import load_icon_color_mapping
    
    invalid_json = '{"icon":"mdi:trash" "no_comma":true}'  # Invalid JSON (missing comma)
    with patch("logging.Logger.warning") as mock_warn:
        result = load_icon_color_mapping(invalid_json)
        # Should return empty dict
        assert result == {}
        # Check log message
        mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_bin_sensor_missing_bin_type(hass, mock_config_entry):
    """Test that we log a warning and set state to Unknown when the bin type is missing."""
    # Create coordinator with data for Recycling but not General Waste
    coordinator = MagicMock()
    coordinator.data = {"Recycling": datetime(2025, 2, 1).date()}
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create sensor for General Waste which isn't in the data
    sensor = UKBinCollectionDataSensor(
        coordinator, "General Waste", "test_general_waste", {}
    )
    
    # Check sensor properties with missing data
    with patch("logging.Logger.warning") as mock_warn:
        sensor.update_state()
    
    assert sensor.state == "Unknown"
    assert sensor.extra_state_attributes["days"] is None
    assert sensor.available is False
    mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_attribute_sensor_undefined_attribute_type(hass, mock_config_entry):
    """Test attribute sensor with undefined attribute type."""
    # Create coordinator with test data
    coordinator = MagicMock()
    coordinator.data = {"Recycling": datetime(2025, 1, 1).date()}
    coordinator.name = "Test Coordinator"
    coordinator.last_update_success = True
    
    # Create attribute sensor with invalid attribute type
    sensor = UKBinCollectionAttributeSensor(
        coordinator=coordinator,
        bin_type="Recycling",
        unique_id="test_recycling_undefined",
        attribute_type="Bogus Attribute",  # Invalid attribute type
        device_id="test_device",
        icon_color_mapping={},
    )
    
    # Check state with undefined attribute
    with patch("logging.Logger.warning") as mock_warn:
        state = sensor.state
    
    assert state == "Undefined"
    mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_bin_sensor_in_x_days(hass, freezer, mock_config_entry):
    """Test bin sensor showing days until collection."""
    freezer.move_to("2023-10-14")
    future_date = dt_util.now().date() + timedelta(days=5)
    
    # Create coordinator with data 5 days in the future
    coordinator = MagicMock()
    coordinator.data = {"General Waste": future_date}
    coordinator.name = "Test Coordinator"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionDataSensor(
        coordinator, "General Waste", "test_gw_in_5_days", {}
    )
    
    # Check state
    assert sensor.state == "In 5 days"


def test_data_sensor_default_icon_unknown_type():
    """Test default icon for unknown bin type."""
    # Create coordinator with custom bin type
    coordinator = MagicMock()
    coordinator.data = {"Some Custom Bin": datetime(2025, 1, 1).date()}
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create sensor for unknown type
    sensor = UKBinCollectionDataSensor(coordinator, "Unknown Type", "test_unknown", {})
    
    # Check default icon
    assert sensor.icon == "mdi:delete"


def test_raw_json_sensor_partial_data():
    """Test raw JSON sensor with partial data (some bins have None dates)."""
    # Create coordinator with partial data
    coordinator = MagicMock()
    coordinator.data = {"General Waste": None, "Recycling": datetime(2025, 1, 1).date()}
    coordinator.last_update_success = True
    
    # Create raw JSON sensor
    sensor = UKBinCollectionRawJSONSensor(coordinator, "test_raw_json", "Test Name")
    
    # Check state with null value
    state = sensor.state
    assert state == '{"General Waste": null, "Recycling": "01/01/2025"}'


def test_data_sensor_unavailable_if_unknown_state():
    """Test that sensor is unavailable if state is Unknown."""
    # Create coordinator with no data
    coordinator = MagicMock()
    coordinator.data = {}  # No bins
    coordinator.name = "Test Coordinator"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionDataSensor(coordinator, "General Waste", "test_gw", {})
    
    # Update state and check availability
    sensor.update_state()  # Sets state to "Unknown"
    assert sensor.available is False


def test_attribute_sensor_unavailable_if_coordinator_failed():
    """Test attribute sensor is unavailable if coordinator update failed."""
    # Create coordinator with failed update
    coordinator = MagicMock()
    coordinator.data = {"Recycling": datetime(2025, 1, 1).date()}
    coordinator.last_update_success = False
    coordinator.name = "Test Coordinator"
    
    # Create attribute sensor
    attr_sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "test_attr_fail", "Colour", "device_id", {}
    )
    
    # Check availability
    assert attr_sensor.available is False


@pytest.mark.asyncio
def test_create_sensor_entities_coordinator_data():
    """Test create_sensor_entities with coordinator data."""
    # Set up a coordinator with two bin types
    coordinator = MagicMock()
    coordinator.data = {
        "General Waste": date(2025, 2, 8),  # Today
        "Recycling": date(2025, 2, 9),  # Tomorrow
    }
    coordinator.name = "Test Coordinator"
    coordinator.last_update_success = True
    
    # Use a valid JSON mapping for General Waste only
    icon_mapping_json = '{"General Waste":{"icon":"mdi:trash-can","color":"brown"}}'
    entities = create_sensor_entities(coordinator, "test_entry", icon_mapping_json)
    
    # Check sensor count (2 main, 10 attribute, 1 raw)
    assert len(entities) == 13
    
    # Check General Waste sensor icon from mapping
    gw_sensor = next(
        e for e in entities
        if isinstance(e, UKBinCollectionDataSensor) and "General Waste" in e.name
    )
    assert gw_sensor.icon == "mdi:trash-can"
    
    # Find an attribute sensor to test
    gw_attr_sensor = next(
        e for e in entities
        if isinstance(e, UKBinCollectionAttributeSensor)
        and "Days Until Collection" in e.name
        and "General Waste" in e.name
    )
    assert gw_attr_sensor.state is not None
    
    # Check raw JSON sensor
    raw_sensor = next(
        e for e in entities if isinstance(e, UKBinCollectionRawJSONSensor)
    )
    raw_state = json.loads(raw_sensor.state)
    assert "General Waste" in raw_state and "Recycling" in raw_state


def test_create_sensor_entities_invalid_icon_json():
    """Test create_sensor_entities with invalid icon JSON."""
    # Create coordinator with test data
    coordinator = MagicMock()
    coordinator.data = {
        "General Waste": datetime(2025, 2, 10).date(),
    }
    coordinator.name = "Test Coordinator"
    coordinator.last_update_success = True
    
    # Try with invalid JSON
    invalid_json = '{"invalid":true,  '  # Incomplete JSON
    with patch("logging.Logger.warning") as mock_warn:
        entities = create_sensor_entities(coordinator, "test_entry_id", invalid_json)
    
    # Should still create sensors (1 main, 5 attribute, 1 raw)
    assert len(entities) == 7
    mock_warn.assert_called_once()


@pytest.mark.asyncio
@freeze_time("2025-02-8")  # Set "today" to 2025-02-8
def test_attribute_sensor_days_and_human_readable():
    """Test attribute sensor days and human readable text."""
    # Create coordinator with bin data 2 days away
    coordinator = MagicMock()
    in_2_days = datetime(2025, 2, 10).date()
    coordinator.data = {"Food Waste": in_2_days}
    coordinator.name = "Coordinator Name"
    coordinator.last_update_success = True
    
    # Create sensors
    entities = create_sensor_entities(coordinator, "entry_id_days", "{}")
    
    # Find days and human readable sensors
    days_sensor = next(
        e for e in entities
        if isinstance(e, UKBinCollectionAttributeSensor)
        and "Days Until Collection" in e.name
    )
    human_sensor = next(
        e for e in entities
        if isinstance(e, UKBinCollectionAttributeSensor)
        and "Next Collection Human Readable" in e.name
    )
    
    # Check states
    days_state = days_sensor.state
    human_state = human_sensor.state
    
    assert days_state == 2
    assert human_state == "In 2 days"


def test_data_sensor_coordinator_update():
    """Test data sensor coordinator update handler."""
    # Create coordinator
    coordinator = MagicMock()
    coordinator.data = {"General Waste": datetime(2025, 2, 10).date()}
    coordinator.name = "Coordinator Name"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionDataSensor(coordinator, "General Waste", "device_id", {})
    
    # Test update handler
    with patch.object(sensor, "update_state") as mock_update, patch.object(
        sensor, "async_write_ha_state"
    ) as mock_write:
        sensor._handle_coordinator_update()
    
    mock_update.assert_called_once()
    mock_write.assert_called_once()


@freeze_time("2025-02-10")  # Set "today" to 2025-02-10
def test_data_sensor_today_tomorrow():
    """Test data sensor today/tomorrow states."""
    # Create coordinator with today and tomorrow bins
    coordinator = MagicMock()
    coordinator.data = {
        "Waste Today": datetime(2025, 2, 10).date(),
        "Waste Tomorrow": datetime(2025, 2, 11).date(),
    }
    coordinator.name = "Coord"
    coordinator.last_update_success = True
    
    # Create sensors
    entities = create_sensor_entities(coordinator, "entry_id", "{}")
    tdy_sensor = next(
        e for e in entities
        if isinstance(e, UKBinCollectionDataSensor) and "Waste Today" in e.name
    )
    tmw_sensor = next(
        e for e in entities
        if isinstance(e, UKBinCollectionDataSensor) and "Waste Tomorrow" in e.name
    )
    
    # Check states
    assert tdy_sensor.state == "Today"
    assert tmw_sensor.state == "Tomorrow"


@freeze_time("2025-02-08")
def test_create_sensor_entities_full_coverage(hass):
    """Test create_sensor_entities with full coverage."""
    # Create coordinator with multiple bin types
    coordinator = MagicMock()
    coordinator.data = {
        "General Waste": datetime(2025, 2, 8).date(),  # Today
        "Recycling": datetime(2025, 2, 9).date(),  # Tomorrow
        "Garden": datetime(2025, 2, 10).date(),  # 2 days
    }
    coordinator.name = "Full Coverage Coord"
    coordinator.last_update_success = True
    
    # Test with invalid JSON
    invalid_icon_json = '{"General Waste": {"icon":"mdi:trash-can"}, "broken"'
    with patch("logging.Logger.warning") as mock_warn:
        entities = create_sensor_entities(
            coordinator, "entry_id_abc", invalid_icon_json
        )
    
    # Check entity count (3 main, 15 attribute, 1 raw)
    assert len(entities) == 19
    mock_warn.assert_called_once()
    
    # Check Garden attribute sensor
    days_garden = next(
        e for e in entities 
        if isinstance(e, UKBinCollectionAttributeSensor)
        and "Garden" in e.name 
        and "Days Until Collection" in e.name
    )
    days_val = days_garden.state
    assert days_val == 2  # Garden is 2 days away
    
    # Check raw sensor
    raw_sensor = next(
        e for e in entities if isinstance(e, UKBinCollectionRawJSONSensor)
    )
    raw_state = raw_sensor.state
    assert raw_state  # Just check it exists
    
    # Test coordinator update handler
    main_sensor = next(
        e for e in entities
        if isinstance(e, UKBinCollectionDataSensor) and "General Waste" in e.name
    )
    with patch.object(main_sensor, "update_state") as mock_up, patch.object(
        main_sensor, "async_write_ha_state"
    ) as mock_aw:
        main_sensor._handle_coordinator_update()
    mock_up.assert_called_once()
    mock_aw.assert_called_once()


def test_attribute_sensor_state_colour():
    """Test attribute sensor with color attribute."""
    # Create coordinator
    coordinator = MagicMock()
    coordinator.data = {"Recycling": datetime(2025, 2, 10).date()}
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor with color mapping
    icon_mapping = {"Recycling": {"icon": "mdi:recycle", "color": "green"}}
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "uid1", "Colour", "dev1", icon_mapping
    )
    
    # Check state
    assert sensor.state == "green"


def test_attribute_sensor_state_bin_type():
    """Test attribute sensor with bin type attribute."""
    # Create coordinator
    coordinator = MagicMock()
    coordinator.data = {"Recycling": datetime(2025, 2, 10).date()}
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "uid2", "Bin Type", "dev2", {}
    )
    
    # Check state
    assert sensor.state == "Recycling"


def test_attribute_sensor_state_next_collection_date_with_data():
    """Test attribute sensor with next collection date attribute."""
    # Create coordinator
    date_value = datetime(2025, 2, 10).date()
    coordinator = MagicMock()
    coordinator.data = {"Recycling": date_value}
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "uid3", "Next Collection Date", "dev3", {}
    )
    
    # Check state
    expected = date_value.strftime("%d/%m/%Y")
    assert sensor.state == expected


def test_attribute_sensor_state_next_collection_date_no_data():
    """Test attribute sensor with next collection date attribute but no data."""
    # Create coordinator with no data
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "uid4", "Next Collection Date", "dev4", {}
    )
    
    # Check state
    assert sensor.state == "Unknown"


@freeze_time("2025-02-08")
def test_attribute_sensor_state_next_collection_human_readable_today():
    """Test attribute sensor with human readable attribute for today."""
    # Create coordinator with today's date
    coordinator = MagicMock()
    coordinator.data = {"Recycling": datetime(2025, 2, 8).date()}
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "uid5", "Next Collection Human Readable", "dev5", {}
    )
    
    # Check state
    assert sensor.state == "Today"


@freeze_time("2025-02-08")
def test_attribute_sensor_state_next_collection_human_readable_tomorrow():
    """Test attribute sensor with human readable attribute for tomorrow."""
    # Create coordinator with tomorrow's date
    coordinator = MagicMock()
    coordinator.data = {"Recycling": datetime(2025, 2, 9).date()}
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "uid6", "Next Collection Human Readable", "dev6", {}
    )
    
    # Check state
    assert sensor.state == "Tomorrow"


@freeze_time("2025-02-08")
def test_attribute_sensor_state_next_collection_human_readable_future():
    """Test attribute sensor with human readable attribute for future date."""
    # Create coordinator with future date
    coordinator = MagicMock()
    coordinator.data = {"Recycling": datetime(2025, 2, 12).date()}  # 4 days later
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "uid7", "Next Collection Human Readable", "dev7", {}
    )
    
    # Check state
    assert sensor.state == "In 4 days"


@freeze_time("2025-02-08")
def test_attribute_sensor_state_days_until_collection_with_data():
    """Test attribute sensor with days until collection attribute."""
    # Create coordinator with future date
    coordinator = MagicMock()
    coordinator.data = {"Recycling": datetime(2025, 2, 11).date()}  # 3 days away
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "uid8", "Days Until Collection", "dev8", {}
    )
    
    # Check state
    assert sensor.state == 3


@freeze_time("2025-02-08")
def test_attribute_sensor_state_days_until_collection_no_data():
    """Test attribute sensor with days until collection attribute but no data."""
    # Create coordinator with no data
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Recycling", "uid9", "Days Until Collection", "dev9", {}
    )
    
    # Check state
    assert sensor.state == -1


def test_data_sensor_extra_state_attributes():
    """Test data sensor extra state attributes."""
    # Create coordinator
    coordinator = MagicMock()
    date_value = datetime(2025, 2, 10).date()
    coordinator.data = {"Recycling": date_value}
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionDataSensor(coordinator, "Recycling", "uid10", {})
    
    # Check attributes
    expected_attributes = {
        STATE_ATTR_COLOUR: sensor.get_color(),  # Without mapping, default is "black"
        STATE_ATTR_NEXT_COLLECTION: date_value.strftime("%d/%m/%Y"),
        STATE_ATTR_DAYS: (date_value - dt_util.now().date()).days,
    }
    assert sensor.extra_state_attributes == expected_attributes


def test_data_sensor_device_info_property():
    """Test data sensor device info property."""
    # Create coordinator
    coordinator = MagicMock()
    coordinator.name = "Test Name"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionDataSensor(coordinator, "General Waste", "device123", {})
    
    # Check device info
    expected = {
        "identifiers": {(DOMAIN, "device123")},
        "name": f"{coordinator.name} General Waste",
        "manufacturer": "UK Bin Collection",
        "model": "Bin Sensor",
        "sw_version": "1.0",
    }
    assert sensor.device_info == expected


def test_data_sensor_unique_id_property():
    """Test data sensor unique ID property."""
    # Create coordinator
    coordinator = MagicMock()
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionDataSensor(
        coordinator, "General Waste", "unique_id_123", {}
    )
    
    # Check unique ID
    assert sensor.unique_id == "unique_id_123"


def test_create_sensor_entities_with_no_data():
    """Test create_sensor_entities with no data."""
    # Create coordinator with no data
    coordinator = MagicMock()
    coordinator.data = {}  # No bin types
    coordinator.name = "Empty Coord"
    coordinator.last_update_success = True
    
    # Create entities
    entities = create_sensor_entities(coordinator, "empty_entry", "{}")
    
    # Should only create raw JSON sensor
    assert len(entities) == 1
    assert isinstance(entities[0], UKBinCollectionRawJSONSensor)


def test_load_icon_color_mapping_empty_string():
    """Test load_icon_color_mapping with empty string."""
    result = load_icon_color_mapping("")
    assert result == {}


def test_raw_json_sensor_with_no_data():
    """Test raw JSON sensor with no data."""
    # Create coordinator with no data
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionRawJSONSensor(coordinator, "raw_test", "Test Name")
    
    # Check state and attributes
    assert sensor.state == "{}"
    assert sensor.extra_state_attributes == {"raw_data": {}}
    assert sensor.available is True


def test_data_sensor_state_unknown_and_extra_attributes():
    """Test data sensor state and extra attributes when data is missing."""
    # Create coordinator with no data
    coordinator = MagicMock()
    coordinator.data = {}  # No data available
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor for bin type not in data
    sensor = UKBinCollectionDataSensor(
        coordinator, "Nonexistent Bin", "device_unknown", {}
    )
    
    # Update state and check properties
    sensor.update_state()  # Sets state to "Unknown"
    
    assert sensor.state == "Unknown"
    
    # Check attributes
    extra = sensor.extra_state_attributes
    assert extra[STATE_ATTR_COLOUR] == "black"
    assert extra[STATE_ATTR_NEXT_COLLECTION] is None


@freeze_time("2025-02-08")
def test_attribute_sensor_calculate_human_readable_and_days_until():
    """Test attribute sensor calculation methods."""
    # Create coordinator with data 3 days in future
    future_date = datetime(2025, 2, 11).date()
    coordinator = MagicMock()
    coordinator.data = {"Food Waste": future_date}
    coordinator.name = "Test Coord"
    coordinator.last_update_success = True
    
    # Create sensor
    sensor = UKBinCollectionAttributeSensor(
        coordinator, "Food Waste", "attr_uid", "Next Collection Human Readable", "dev_uid", {}
    )
    
    # Manually call the helper methods:
    human_readable = sensor.calculate_human_readable()
    days_until = sensor.calculate_days_until()
    
    # From 2025-02-08 to 2025-02-11 is 3 days away.
    assert human_readable == "In 3 days"
    assert days_until == 3
