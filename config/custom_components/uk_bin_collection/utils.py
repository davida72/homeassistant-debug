import json
import aiohttp
import logging
import asyncio
import voluptuous as vol
import shutil
import re

from voluptuous import Schema, Required, Optional
from typing import List, Dict, Any

from typing import Dict, Any, Optional
from .const import BROWSER_BINARIES
from homeassistant import config_entries

_LOGGER = logging.getLogger(__name__)

# -----------------------------------------------------
# 🔄 Fetch Data
# -----------------------------------------------------

async def get_councils_json(url: str = None) -> Dict[str, Any]:
    """
    Fetch council data from a JSON URL.
    
    This function can handle both data formats:
    - Old format (input.json): Where GooglePublicCalendarCouncil contains supported_councils
    - New format (placeholder_input.json): Where councils directly reference GooglePublicCalendarCouncil 
      via original_parser
    
    This function ensures the output is consistent regardless of input format, maintaining
    the same user experience by preserving council names in the wiki_name field.
    
    Args:
        url: URL to fetch councils data from. If None, uses the default URL from constants.
    
    Returns:
        Dictionary of council data, sorted alphabetically by council ID.
    """
    from .const import COUNCIL_DATA_URL
    
    if url is None:
        url = COUNCIL_DATA_URL
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                response.raise_for_status()
                data_text = await response.text()
                council_data = json.loads(data_text)
                
                # Check if we're dealing with the old format by looking for supported_councils in GooglePublicCalendarCouncil
                is_old_format = "GooglePublicCalendarCouncil" in council_data and "supported_councils" in council_data["GooglePublicCalendarCouncil"]
                
                normalized_data = {}
                
                if is_old_format:
                    _LOGGER.debug("Detected old format JSON (input.json style)")
                    # Process old format
                    for key, value in council_data.items():
                        normalized_data[key] = value
                        # If this is GooglePublicCalendarCouncil, process its supported councils
                        if key == "GooglePublicCalendarCouncil" and "supported_councils" in value:
                            for alias in value.get("supported_councils", []):
                                alias_data = value.copy()
                                alias_data["original_parser"] = key
                                alias_data["wiki_command_url_override"] = "https://calendar.google.com/calendar/ical/XXXXX%40group.calendar.google.com/public/basic.ics"
                                # Set wiki_name without any suffix for consistency
                                alias_data["wiki_name"] = alias.replace('Council', ' Council')
                                # Preserve wiki_note if it exists
                                if "wiki_note" in value:
                                    alias_data["wiki_note"] = value["wiki_note"]
                                normalized_data[alias] = alias_data
                else:
                    _LOGGER.debug("Detected new format JSON (placeholder_input.json style)")
                    # Process new format - all councils are already first-class entries with their own complete data
                    normalized_data = council_data.copy()
                    # No special handling needed for GooglePublicCalendarCouncil councils
                    # as they're already properly defined in the new format
                
                # Sort alphabetically by key (council ID)
                sorted_data = dict(sorted(normalized_data.items()))
                
                _LOGGER.debug("Loaded %d councils", len(sorted_data))
                return sorted_data
            
    except aiohttp.ClientError as e:
        _LOGGER.error("HTTP error fetching council data: %s", e)
        return {}
    except asyncio.TimeoutError:
        _LOGGER.error("Timeout fetching council data from %s", url)
        return {}
    except json.JSONDecodeError as e:
        _LOGGER.error("Invalid JSON in council data: %s", e)
        return {}
    except Exception as e:
        _LOGGER.error("Unexpected error fetching council data: %s", e)
        return {}

async def check_selenium_server(url: str) -> bool:
    """Check if a Selenium server is accessible."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=5) as response:
                accessible = response.status == 200
                # _LOGGER.debug(f"Selenium server at {url} is {'accessible' if accessible else 'not accessible'}")
                return accessible
        except Exception as e:
            # _LOGGER.debug(f"Error checking Selenium server at {url}: {e}")
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
            _LOGGER.debug(
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
    _LOGGER.debug(f"Building schema with default_name={default_name}, default_council={default_council}")
    
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
        fields[vol.Required("uprn", default=defaults.get("uprn", ""))] = str
    if "house_number" in council_data:
        fields[vol.Required("house_number", default=defaults.get("house_number", ""))] = str
    if "usrn" in council_data:
        fields[vol.Required("usrn", default=defaults.get("usrn", ""))] = str
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

def build_advanced_schema(defaults=None) -> Schema:
    """Schema for advanced settings configuration."""
    if defaults is None:
        defaults = {}
        
    _LOGGER.debug("Building advanced schema with defaults: %s", defaults)
    return Schema({
        vol.Optional("manual_refresh_only", default=defaults.get("manual_refresh_only", True)): bool,
        vol.Optional("update_interval", default=defaults.get("update_interval", 12)): int,
        vol.Optional("timeout", default=defaults.get("timeout", 60)): int,
        vol.Optional("icon_color_mapping", default=defaults.get("icon_color_mapping", "")): str
    })


def build_options_schema(existing_data, council_options, council_names):
    """Build schema for the options flow."""
    # Find the current council's wiki_name
    council_key = existing_data.get("council", "")
    council_index = council_names.index(council_key) if council_key in council_names else 0
    selected_wiki_name = council_options[council_index] if council_index < len(council_options) else ""
    
    # Create schema
    return vol.Schema(
        {
            vol.Required("council", default=selected_wiki_name): vol.In(council_options),
            vol.Required("timeout", default=existing_data.get("timeout", 60)): int,
            vol.Optional("update_interval", default=existing_data.get("update_interval", 12)): int,
            vol.Optional("manual_refresh_only", default=existing_data.get("manual_refresh_only", False)): bool,
            vol.Optional("icon_color_mapping", default=existing_data.get("icon_color_mapping", "")): str,
        }
    )


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
        _LOGGER.debug(f"Invalid JSON string: {e}")
        return False
    
async def async_entry_exists(
    flow, user_input: Dict[str, Any]
) -> Optional[config_entries.ConfigEntry]:
    """Check if a config entry with the same name or data already exists."""
    for entry in flow._async_current_entries():
        if entry.data.get("name") == user_input.get("name"):
            return entry
        if entry.data.get("council") == user_input.get("council") and entry.data.get("url") == user_input.get("url"):
            return entry
    return None

def map_wiki_name_to_council_key(wiki_name, council_options, council_names):
    """Maps a wiki_name back to the council key."""
    try:
        index = council_options.index(wiki_name)
        return council_names[index]
    except (ValueError, IndexError):
        _LOGGER.warning(f"Could not map wiki_name '{wiki_name}' to council key")
        return wiki_name  # Return the wiki_name as fallback
    
def is_valid_postcode(postcode: str) -> bool:
    # UK postcode regex pattern
    postcode_regex = r"^(GIR 0AA|[A-PR-UWYZ][A-HK-Y]?[0-9][0-9A-HJKSTUW]? ?[0-9][ABD-HJLNP-UW-Z]{2})$"
    return re.match(postcode_regex, postcode.replace(" ", "").upper()) is not None

    # Examples
    #print(is_valid_postcode("SW1A 1AA"))  # True
    #print(is_valid_postcode("INVALID"))   # False

def is_valid_uprn(uprn: str) -> bool:
    return uprn.isdigit() and len(uprn) <= 12
    
    # Examples
    # print(is_valid_uprn("100021066689"))  # True
    # print(is_valid_uprn("ABCD12345678"))  # False
