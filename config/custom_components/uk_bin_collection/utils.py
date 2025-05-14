import json
import aiohttp
import logging
import asyncio
import voluptuous as vol
import shutil

from voluptuous import Schema, Required, Optional
from typing import List, Dict, Any
from .const import BROWSER_BINARIES

_LOGGER = logging.getLogger(__name__)

# -----------------------------------------------------
# 🔄 Fetch Data
# -----------------------------------------------------

async def get_councils_json(url: str) -> Dict[str, Any]:
    """Fetch and normalize council data from a JSON URL."""
    
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

async def check_selenium_server(url: str) -> bool:
    """Check if a Selenium server is accessible."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=5) as response:
                accessible = response.status == 200
                _LOGGER.debug(f"Selenium server at {url} is {'accessible' if accessible else 'not accessible'}")
                return accessible
        except Exception as e:
            _LOGGER.error(f"Error checking Selenium server at {url}: {e}")
            return False

async def check_chromium_installed() -> bool:
    """Check if Chromium is installed."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _sync_check_chromium)
    if result:
        _LOGGER.debug("Chromium is installed.")
    else:
        _LOGGER.debug("Chromium is not installed.")
    return result

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

# -----------------------------------------------------
# 🔄 Schema Builders
# -----------------------------------------------------

def build_user_schema(wiki_names, default_name="", default_council=None):
    """Build schema for the user step of the config flow."""
    
    # For debugging
    print(f"Building schema with default_name={default_name}, default_council={default_council}")
    
    return vol.Schema({
        vol.Required("name", default=default_name): str,
        vol.Required("selected_council", default=default_council): vol.In(wiki_names)
    })


def build_council_schema(council_key: str, council_data: Dict[str, Any], defaults: Dict[str, str] = {}) -> Schema:
    """Schema for configuring council-specific information."""
    fields = {}
    if "postcode" in council_data:
        fields[vol.Required("postcode", default=defaults.get("postcode", ""))] = str
    if "uprn" in council_data:
        fields[vol.Required("uprn")] = str
    if "house_number" in council_data:
        fields[vol.Required("house_number")] = str
    if "usrn" in council_data:
        fields[vol.Required("usrn")] = str
    if "wiki_command_url_override" in council_data:
        fields[vol.Optional("url", default=defaults.get("url", ""))] = str

    _LOGGER.debug(f"Building council schema for {council_key} with fields: {list(fields.keys())}")
    return Schema(fields)


def build_selenium_schema(default_url=""):
    """Build schema for Selenium configuration."""
    import homeassistant.helpers.config_validation as cv
    
    # Create the schema with separate options instead of multi-select
    return vol.Schema({
        vol.Optional("web_driver", default=default_url): vol.Coerce(str),
        vol.Optional("headless_mode", default=True): bool,
        vol.Optional("local_browser", default=False): bool,
    })

def build_advanced_schema() -> Schema:
    """Schema for advanced settings configuration."""
    _LOGGER.debug("Building advanced schema")
    return Schema({
        vol.Optional("manual_refresh_only", default=True): bool,
        vol.Optional("update_interval", default=12): int,
        vol.Optional("timeout", default=60): int,
        vol.Optional("icon_color_mapping", default=""): str
    })


# -----------------------------------------------------
# 🔄 Utility Functions
# -----------------------------------------------------

def is_valid_json(json_string: str) -> bool:
    """Check if a string is valid JSON."""
    try:
        json.loads(json_string)
        _LOGGER.debug("JSON string is valid.")
        return True
    except ValueError as e:
        _LOGGER.error(f"Invalid JSON string: {e}")
        return False