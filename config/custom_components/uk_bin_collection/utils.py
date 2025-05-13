import json
import logging
import shutil
import asyncio
from typing import Any, Dict, List, Optional

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries

from .const import SELENIUM_SERVER_URLS, BROWSER_BINARIES

_LOGGER = logging.getLogger(__name__)

"""JSON validation function"""

def is_valid_json(json_str: str) -> bool:
    """Validate if a string is valid JSON."""
    try:
        json.loads(json_str)
        return True
    except json.JSONDecodeError as e:
        _LOGGER.debug("JSON decode error in options flow: %s", e)
        return False

"""Selenium and browser-related functions"""

async def check_chromium_installed() -> bool:
    """Check if Chromium is installed."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _sync_check_chromium)
    if result:
        _LOGGER.debug("Chromium is installed.")
    else:
        _LOGGER.debug("Chromium is not installed.")
    return result

async def check_selenium_server(url: str) -> tuple:
    """Check if a single Selenium server is accessible."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=5) as response:
                response.raise_for_status()
                accessible = response.status == 200
                _LOGGER.debug("Selenium server %s is accessible.", url)
                return url, accessible
        except aiohttp.ClientError as e:
            _LOGGER.warning("Failed to connect to Selenium server at %s: %s", url, e)
            return url, False
        except Exception as e:
            _LOGGER.exception("Unexpected error checking Selenium server at %s: %s", url, e)
            return url, False

def _sync_check_chromium() -> bool:
    """Synchronous check for Chromium installation."""
    for exec_name in BROWSER_BINARIES:
        try:
            if shutil.which(exec_name):
                _LOGGER.debug(f"Found Chromium executable: {exec_name}")
                return True
        except Exception as e:
            _LOGGER.error(
                f"Exception while checking for executable '{exec_name}': {e}"
            )
            continue  # Continue checking other binaries
    _LOGGER.debug("No Chromium executable found.")
    return False

"""Schema building functions"""

def get_council_schema(council: str, councils_data: Dict) -> vol.Schema:
    """Generate the form schema based on council requirements."""
    council_info = councils_data.get(council, {})
    fields = {}

    if not council_info.get("skip_get_url", False) or council_info.get(
        "custom_component_show_url_field"
    ):
        fields[vol.Required("url")] = cv.string
    if "uprn" in council_info:
        fields[vol.Required("uprn")] = cv.string
    if "postcode" in council_info:
        fields[vol.Required("postcode")] = cv.string
    if "house_number" in council_info:
        fields[vol.Required("number")] = cv.string
    if "usrn" in council_info:
        fields[vol.Required("usrn")] = cv.string
    if "web_driver" in council_info:
        fields[vol.Optional("web_driver", default="")] = cv.string
        fields[vol.Optional("headless", default=True)] = bool
        fields[vol.Optional("local_browser", default=False)] = bool

    fields[vol.Optional("timeout", default=60)] = vol.All(
        vol.Coerce(int), vol.Range(min=10)
    )

    fields[vol.Optional("update_interval", default=12)] = vol.All(
        cv.positive_int, vol.Range(min=1)
    )

    return vol.Schema(fields)

def build_reconfigure_schema(
    existing_data: Dict[str, Any], council_wiki_name: str, council_options: List[str]
) -> vol.Schema:
    """Build the schema for reconfiguration with existing data."""
    fields = {
        vol.Required("name", default=existing_data.get("name", "")): str,
        vol.Required("council", default=council_wiki_name): vol.In(council_options),
        vol.Optional(
            "manual_refresh_only",
            default=existing_data.get("manual_refresh_only", False),
        ): bool,
        vol.Required(
            "update_interval", default=existing_data.get("update_interval", 12)
        ): vol.All(cv.positive_int, vol.Range(min=1)),
    }

    optional_fields = [
        ("url", cv.string),
        ("uprn", cv.string),
        ("postcode", cv.string),
        ("number", cv.string),
        ("web_driver", cv.string),
        ("headless", bool),
        ("local_browser", bool),
        ("timeout", vol.All(vol.Coerce(int), vol.Range(min=10))),
    ]

    for field_name, validator in optional_fields:
        if field_name in existing_data:
            fields[vol.Optional(field_name, default=existing_data[field_name])] = validator

    fields[
        vol.Optional(
            "icon_color_mapping",
            default=existing_data.get("icon_color_mapping", ""),
        )
    ] = str

    return vol.Schema(fields)

def build_council_info_schema(council_key: str, councils_data: Dict) -> vol.Schema:
    """Build schema for council-specific information."""
    council_info = councils_data.get(council_key, {})
    fields = {}
    
    # Add required fields based on council requirements
    if not council_info.get("skip_get_url", False):
        fields[vol.Required("url")] = cv.string
    if "uprn" in council_info:
        fields[vol.Required("uprn")] = cv.string
    if "postcode" in council_info:
        fields[vol.Required("postcode")] = cv.string
    if "house_number" in council_info:
        fields[vol.Required("number")] = cv.string
    if "usrn" in council_info:
        fields[vol.Required("usrn")] = cv.string
        
    # Return schema with the fields or an empty schema if no fields
    if not fields:
        fields[vol.Optional("none_required", default=True)] = vol.Boolean(False)
        
    return vol.Schema(fields)

def build_options_schema(
    existing_data: Dict[str, Any], 
    council_options: List[str],
    council_names: List[str]
) -> vol.Schema:
    """Build the schema for the options flow with existing data."""
    council_current_key = existing_data.get("council", "")
    try:
        council_current_wiki = council_options[
            council_names.index(council_current_key)
        ]
    except (ValueError, IndexError):
        council_current_wiki = ""

    fields = {
        vol.Required("name", default=existing_data.get("name", "")): str,
        vol.Required("council", default=council_current_wiki): vol.In(council_options),
        vol.Optional(
            "manual_refresh_only",
            default=existing_data.get("manual_refresh_only", False),
        ): bool,
        vol.Required(
            "update_interval", default=existing_data.get("update_interval", 12)
        ): vol.All(cv.positive_int, vol.Range(min=1)),
    }

    optional_fields = [
        ("icon_color_mapping", cv.string),
        # Add other optional fields if necessary
    ]

    for field_name, validator in optional_fields:
        if field_name in existing_data:
            fields[vol.Optional(field_name, default=existing_data[field_name])] = validator

    return vol.Schema(fields)

"""Data retrieval and processing functions"""

async def get_councils_json(url: str = None) -> Dict[str, Any]:
    """
    Fetch and return the supported councils data, including aliases and sorted alphabetically.
    
    Args:
        url: URL to fetch councils data from. If None, uses the default URL.
    
    Returns:
        Dictionary of council data.
    """
    if url is None:
        url = "https://raw.githubusercontent.com/robbrad/UKBinCollectionData/0.152.0/uk_bin_collection/tests/input.json"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data_text = await response.text()
                original_data = json.loads(data_text)
                _LOGGER.debug("Raw council data: %s", original_data)

                normalized_data = {}
                for key, value in original_data.items():
                    normalized_data[key] = value
                    for alias in value.get("supported_councils", []):
                        alias_data = value.copy()
                        alias_data["original_parser"] = key
                        alias_data["wiki_name"] = (
                            f"{alias.replace('Council', ' Council')} (via Google Calendar)"
                        )
                        normalized_data[alias] = alias_data

                # Sort alphabetically by key (council ID)
                sorted_data = dict(sorted(normalized_data.items()))

                _LOGGER.debug(
                    "Loaded and sorted %d councils (with aliases)", len(sorted_data)
                )
                return sorted_data
    except Exception as e:
        _LOGGER.error("Failed to fetch councils data from %s: %s", url, e)
        return {}

"""Council mapping function"""

def map_wiki_name_to_council_key(wiki_name: str, council_options: List[str], council_names: List[str]) -> str:
    """Map the council wiki name back to the council key."""
    try:
        index = council_options.index(wiki_name)
        council_key = council_names[index]
        _LOGGER.debug(
            "Mapped wiki name '%s' to council key '%s'.", wiki_name, council_key
        )
        return council_key
    except ValueError:
        _LOGGER.error("Wiki name '%s' not found in council options.", wiki_name)
        return ""

"""Entry validation function"""

async def async_entry_exists(
    flow, user_input: Dict[str, Any]
) -> Optional[config_entries.ConfigEntry]:
    """Check if a config entry with the same name or data already exists."""
    for entry in flow._async_current_entries():
        if entry.data.get("name") == user_input.get("name"):
            return entry
        if entry.data.get("council") == user_input.get(
            "council"
        ) and entry.data.get("url") == user_input.get("url"):
            return entry
    return None