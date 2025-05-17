"""Options flow for UK Bin Collection integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .initialisation import initialisation_data
from .utils import (
    build_user_schema,
    build_council_schema,
    build_selenium_schema,
    build_advanced_schema,
    check_chromium_installed,
    check_selenium_server,
    is_valid_json,
    prepare_config_data
)

_LOGGER = logging.getLogger(__name__)

class UkBinCollectionOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for UkBinCollection."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self.data = dict(config_entry.data)
        self._initialized = False
        
        # IMPORTANT: Ensure council is initialized from the start
        # If council doesn't exist in config data but original_parser does, use that
        if not self.data.get("council") and self.data.get("original_parser"):
            self.data["council"] = self.data["original_parser"]
            
        # Log the initial state for debugging
        _LOGGER.debug(f"Options flow initialized with council: {self.data.get('council')}, original_parser: {self.data.get('original_parser')}")
        
    async def async_step_init(self, user_input=None):
        """First step in options flow - redirect to user selection."""
        # Initialize the handler with councils data
        if not self._initialized:
            await initialisation_data(self)
            self._initialized = True
            
        # Redirect to the first step (user selection)
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Step 1: Select Council."""
        errors = {}
        
        # Create a mapping of wiki names to council keys
        council_list = self.data.get("council_list", {})
        wiki_names_map = {}
        
        for council_key, council_data in council_list.items():
            wiki_name = council_data.get("wiki_name", council_key)
            wiki_names_map[wiki_name] = council_key
        
        # Sort wiki names for the dropdown
        wiki_names = sorted(wiki_names_map.keys())
        
        # Get the current council key and original parser from the config entry
        current_council_key = self.data.get("council", "")
        current_original_parser = self.data.get("original_parser", "")
        current_wiki_name = None
        
        # Debug logging to see what we're working with
        _LOGGER.debug(f"Looking up council for: council={current_council_key}, original_parser={current_original_parser}")
        
        for wiki_name, council_key in wiki_names_map.items():

            # Match by exact council key
            if council_key == current_council_key:
                current_wiki_name = wiki_name
                _LOGGER.debug(f"Found council by exact match: {wiki_name}")
                break
            
        # Log the result
        if current_wiki_name:
            _LOGGER.debug(f"Using {current_wiki_name} as the selected council")
        else:
            _LOGGER.warning(f"Could not find matching council for {current_council_key}")
        
        # Get default name
        current_name = self.data.get("name", "")
        
        schema = build_user_schema(
            wiki_names=wiki_names,
            default_name=current_name,
            default_council=current_wiki_name,
            include_test_data=True 
        )
        
        if user_input is not None:
            selected_wiki_name = user_input.get("selected_council")
            council_key = wiki_names_map.get(selected_wiki_name)
            
            # Update the data with both the display name and internal key
            self.data["name"] = user_input.get("name")
            self.data["selected_wiki_name"] = selected_wiki_name
            self.data["selected_council"] = council_key
            
            # Store whether to use test data
            self.data["use_test_data"] = user_input.get("use_test_data", False)

            # Preserve the original_parser if present in council data
            council_data = council_list.get(council_key, {})
            if "original_parser" in council_data:
                self.data["original_parser"] = council_data["original_parser"]
                _LOGGER.debug(f"Using original_parser '{council_data['original_parser']}' for council {council_key}")
            
            if not errors:
                return await self.async_step_council_info()

        # Dynamically set the description placeholders
        description_placeholders = {
            "step_user_description": "Modify your bin collection configuration."
        }

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )
    
    async def async_step_council_info(self, user_input=None):
        """Step 2: Configure Council Information."""
        errors = {}

        council_key = self.data.get("selected_council", "")
        council_data = self.data.get("council_list", {}).get(council_key, {})
        wiki_command_url_override = council_data.get("wiki_command_url_override", "")

        if user_input is not None:
            # Check if URL is required and hasn't been modified
            if user_input.get("url") == wiki_command_url_override and wiki_command_url_override:
                errors["base"] = "url_not_modified"
                _LOGGER.warning("URL was not modified but is required for this council")
            
            if not errors:
                self.data.update(user_input)
                council_key = self.data.get("selected_council", "")
                council_data = self.data.get("council_list", {}).get(council_key, {})

                # If this council does not require Selenium, skip to advanced
                if not council_data.get("web_driver"):
                    return await self.async_step_advanced()
                return await self.async_step_selenium()

        # Get current values from config entry
        default_values = {
            "postcode": self.data.get("postcode", ""),
            "uprn": self.data.get("uprn", ""),
            "house_number": self.data.get("number", ""),  # 'number' in final data, 'house_number' in schema
            "usrn": self.data.get("usrn", ""),
            "url": self.data.get("url", wiki_command_url_override)
        }

        # If user selected to use test data, replace with values from council_data
        if self.data.get("use_test_data", False):
            _LOGGER.debug(f"Using test data for council {council_key}")
            
            # Map the test data fields to the form fields
            if "postcode" in council_data:
                default_values["postcode"] = council_data["postcode"]
            if "house_number" in council_data:
                default_values["house_number"] = council_data["house_number"]
            if "uprn" in council_data:
                default_values["uprn"] = council_data["uprn"]
            if "usrn" in council_data:
                default_values["usrn"] = council_data["usrn"]
            if "url" in council_data:
                default_values["url"] = council_data["url"]
                
            _LOGGER.debug(f"Test data values: {default_values}")

        wiki_note = council_data.get("wiki_note", "No additional notes available for this council.")
        
        description_placeholders = {
            "step_council_info_description": wiki_note
        }

        schema = build_council_schema(council_key, council_data, default_values)

        return self.async_show_form(
            step_id="council_info",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_selenium(self, user_input=None):
        """Step 3: Selenium configuration."""
        
        errors = {}

        # Initialize selenium_status if missing
        if "selenium_status" not in self.data:
            self.data["selenium_status"] = {}

        # Get current selenium settings
        current_web_driver = self.data.get("web_driver", "")
        current_headless = self.data.get("headless", True)
        current_local_browser = self.data.get("local_browser", False)
        
        # Use the schema builder instead of manually creating a schema
        schema = build_selenium_schema(default_url=current_web_driver)

        if user_input is not None:
            self.data.update(user_input)
            
            # Get user selections
            use_local_browser = user_input.get("local_browser", False)
            web_driver_url = user_input.get("web_driver", "").strip()
            
            # Check if Selenium server is accessible
            if web_driver_url:
                is_accessible = await check_selenium_server(web_driver_url)

                if is_accessible:
                    _LOGGER.debug(f"Selected Selenium URL {web_driver_url} is accessible")
                    # Selenium URL is accessible, proceed to the next step
                    return await self.async_step_advanced()
                else:
                    errors["base"] = "selenium_unavailable"
                    _LOGGER.debug(f"Selected Selenium URL {web_driver_url} is NOT accessible")
            elif use_local_browser:
                # Check if Chromium is installed
                chromium_installed = await check_chromium_installed()
                self.data["chromium_installed"] = chromium_installed

                if chromium_installed:
                    _LOGGER.debug("Local browser selected and Chromium is available")
                    # Chromium is available, proceed to the next step
                    return await self.async_step_advanced()
                else:
                    errors["base"] = "chromium_unavailable"
                    _LOGGER.debug("Local browser selected but Chromium is not installed")
            else:
                # Neither Selenium nor Chromium is available
                errors["base"] = "selenium_unavailable"
                _LOGGER.debug("No Selenium method selected (neither URL provided nor local browser enabled)")

            # If everything is valid, proceed to the next step
            if not errors:
                return await self.async_step_advanced()

        description_placeholders = {}

        return self.async_show_form(
            step_id="selenium",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_advanced(self, user_input=None):
        """Step 4: Advanced configuration."""
        errors = {}
        
        # Get current advanced settings
        advanced_defaults = {
            "manual_refresh_only": self.data.get("manual_refresh_only", True),
            "update_interval": self.data.get("update_interval", 12),
            "timeout": self.data.get("timeout", 60),
            "icon_color_mapping": self.data.get("icon_color_mapping", "")
        }
        
        # Use the schema builder instead of manually creating a schema
        schema = build_advanced_schema(defaults=advanced_defaults)

        if user_input is not None:
            # Check if icon_color_mapping is valid JSON if provided
            if user_input.get("icon_color_mapping"):
                if not is_valid_json(user_input["icon_color_mapping"]):
                    errors["icon_color_mapping"] = "invalid_json"
                    _LOGGER.warning("Invalid JSON in icon_color_mapping field")
            
            if not errors:
                # Update the data with the user input
                self.data.update(user_input)
                
                try:
                    # Use the shared function to prepare the data
                    filtered_data = prepare_config_data(self.data)
                    
                    # Update the config entry with the new data
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data=filtered_data
                    )
                    
                    # Trigger a reload for the config entry
                    await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                    _LOGGER.info(f"Successfully updated and reloaded config entry {self.config_entry.entry_id}")
                    
                except ValueError as e:
                    return self.async_show_form(
                        step_id="advanced",
                        data_schema=schema,
                        errors=errors
                    )
                except Exception as e:
                    _LOGGER.exception(f"Error updating config entry: {e}")
                    errors["base"] = "update_failed"
                    return self.async_show_form(
                        step_id="advanced",
                        data_schema=schema,
                        errors=errors
                    )
                
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            errors=errors
        )