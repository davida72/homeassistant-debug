"""Test UK Bin Collection utility functions."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from custom_components.uk_bin_collection.utils import (
    calculate_days_until,
    format_date,
    get_bin_type_to_color_mapping,
    get_unique_types,
    find_next_collection_date,
)


def test_calculate_days_until():
    """Test calculating days until a date."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)
    next_week = today + timedelta(days=7)
    
    # Test today
    assert calculate_days_until(today) == 0
    
    # Test tomorrow
    assert calculate_days_until(tomorrow) == 1
    
    # Test yesterday (should be negative)
    assert calculate_days_until(yesterday) == -1
    
    # Test next week
    assert calculate_days_until(next_week) == 7
    
    # Test with datetime object (should extract just the date)
    dt = datetime.combine(tomorrow, datetime.min.time())
    assert calculate_days_until(dt) == 1


def test_format_date():
    """Test date formatting."""
    test_date = date(2023, 5, 15)  # May 15, 2023
    
    # Test default format
    assert format_date(test_date) == "Monday, May 15, 2023"
    
    # Test custom format
    assert format_date(test_date, "%Y-%m-%d") == "2023-05-15"
    
    # Test with datetime object
    test_datetime = datetime(2023, 5, 15, 12, 30, 45)
    assert format_date(test_datetime) == "Monday, May 15, 2023"


def test_get_bin_type_to_color_mapping():
    """Test getting bin type to color mapping."""
    # Test with valid mapping
    valid_mapping = {
        "General Waste": {"icon": "mdi:trash-can", "color": "brown"},
        "Recycling": {"icon": "mdi:recycle", "color": "green"}
    }
    
    result = get_bin_type_to_color_mapping(valid_mapping)
    assert result == {
        "General Waste": "brown",
        "Recycling": "green"
    }
    
    # Test with empty mapping
    assert get_bin_type_to_color_mapping({}) == {}
    
    # Test with mapping that has missing color
    incomplete_mapping = {
        "General Waste": {"icon": "mdi:trash-can"}  # No color
    }
    
    result = get_bin_type_to_color_mapping(incomplete_mapping)
    assert "General Waste" not in result  # Should not include the item


def test_get_unique_types():
    """Test getting unique bin types from collection data."""
    collection_data = [
        {"type": "General Waste", "collectionDate": "2023-05-15"},
        {"type": "Recycling", "collectionDate": "2023-05-16"},
        {"type": "General Waste", "collectionDate": "2023-05-22"},  # Duplicate type
        {"type": "Garden", "collectionDate": "2023-05-23"},
    ]
    
    result = get_unique_types(collection_data)
    assert sorted(result) == sorted(["General Waste", "Recycling", "Garden"])
    assert len(result) == 3  # Should have 3 unique types


def test_get_unique_types_empty():
    """Test get_unique_types with empty data."""
    assert get_unique_types([]) == []


def test_find_next_collection_date():
    """Test finding the next collection date."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    next_week = today + timedelta(days=7)
    
    collection_data = [
        {"type": "General Waste", "collectionDate": today.isoformat()},
        {"type": "Recycling", "collectionDate": tomorrow.isoformat()},
        {"type": "Garden", "collectionDate": next_week.isoformat()},
    ]
    
    # Test finding the next collection from today
    result = find_next_collection_date(collection_data)
    assert result["collectionDate"] == today.isoformat()
    assert result["type"] == "General Waste"
    
    # Test finding the next collection from tomorrow
    result = find_next_collection_date(collection_data, from_date=tomorrow)
    assert result["collectionDate"] == tomorrow.isoformat()
    assert result["type"] == "Recycling"
    
    # Test with empty data
    assert find_next_collection_date([]) is None
    
    # Test when all collections are in the past
    past_data = [
        {"type": "General Waste", "collectionDate": (today - timedelta(days=2)).isoformat()},
        {"type": "Recycling", "collectionDate": (today - timedelta(days=1)).isoformat()},
    ]
    assert find_next_collection_date(past_data, from_date=today) is None