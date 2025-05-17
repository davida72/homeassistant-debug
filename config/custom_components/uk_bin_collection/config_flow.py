from homeassistant import config_entries
from homeassistant.core import callback
from .initialisation import initialisation_data
from .options_flow import UkBinCollectionOptionsFlowHandler

import logging
from .utils import (
    build_user_schema,
    build_council_schema,
    build_selenium_schema,
    build_advanced_schema,
    async_entry_exists,
    check_chromium_installed,
    check_selenium_server,
    is_valid_json
)

_LOGGER = logging.getLogger(__name__)

class BinCollectionConfigFlow(config_entries.ConfigFlow, domain="uk_bin_collection"):
    """Config flow for Bin Collection Data."""
    
    VERSION = 3
    
    def __init__(self):
        """Initialize the config flow."""
        self.data = {}
        self._initialized = False
        self.options_flow = False  # Flag to indicate if this is being used in options flow

    async def async_step_user(self, user_input=None):
        """Step 1: Select Council."""
        
        errors = {}
        
        # Only run initialization once if not already initialized
        if not self._initialized:
            await initialisation_data(self)
            self._initialized = True
        
        # Create a mapping of wiki names to council keys
        council_list = self.data.get("council_list", {})
        wiki_names_map = {}
        
        for council_key, council_data in council_list.items():
            wiki_name = council_data.get("wiki_name", council_key)
            wiki_names_map[wiki_name] = council_key
        
        # Sort wiki names for the dropdown
        wiki_names = sorted(wiki_names_map.keys())
        
        # Get detected council name (if available)
        detected_council_key = self.data.get("detected_council", None)
        detected_council_name = None
        if detected_council_key and detected_council_key in council_list:
            detected_council_name = council_list[detected_council_key].get("wiki_name")
        
        # Get default name (street name from property info)
        default_name = self.data.get("property_info", {}).get("street_name", "")

        council_key = self.data.get("selected_council", "")
        if council_key in council_list:
            default_council = council_list[council_key].get("wiki_name", council_key)
        else:
            default_council = detected_council_name or ""
                
        schema = build_user_schema(
            wiki_names=wiki_names,
            default_name=self.data.get("name", default_name),
            default_council=default_council
        )

        if user_input is not None:
            selected_wiki_name = user_input.get("selected_council")
            council_key = wiki_names_map.get(selected_wiki_name)
            
            # Update the data with both the display name and internal key
            self.data["name"] = user_input.get("name")
            self.data["selected_wiki_name"] = selected_wiki_name
            self.data["selected_council"] = council_key
            
            # Preserve the original_parser if present in council data
            council_data = council_list.get(council_key, {})
            if "original_parser" in council_data:
                self.data["original_parser"] = council_data["original_parser"]
                _LOGGER.debug(f"Using original_parser '{council_data['original_parser']}' for council {council_key}")
            
            # Only check for duplicates if this is a new entry (not options flow)
            if not self.options_flow:
                existing_entry = await async_entry_exists(self, user_input)
                if existing_entry:
                    errors["base"] = "duplicate_entry"
                    _LOGGER.warning(
                        "Duplicate entry found: %s", existing_entry.data.get("name")
                    )
            
            if not errors:
                return await self.async_step_council_info()

        # Dynamically set the description placeholders
        description_placeholders = {}
        if detected_council_name and not self.options_flow:
            description_placeholders["step_user_description"] = "Council auto-selected based on location."
            _LOGGER.debug("Detected council: %s", detected_council_name)
        else:
            description_placeholders["step_user_description"] = f"Please [contact us](https://github.com/robbrad/UKBinCollectionData#requesting-your-council) if your council isn't listed."
            _LOGGER.debug("No council detected or in options flow mode.")

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
        wiki_command_url = council_data.get("wiki_command_url_override", "")

        if user_input is not None:
            # Check if URL is required and hasn't been modified
            if user_input.get("url") == wiki_command_url and wiki_command_url:
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

        default_values = {
            "postcode": self.data.get("detected_postcode", self.data.get("postcode", "")),
            "url": self.data.get("url", wiki_command_url)
        }

        wiki_note = council_data.get("wiki_note", "No additional notes available for this council.")
        
        description_placeholders = {}
        description_placeholders["step_council_info_description"] = wiki_note

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

        # Debug to see what's in self.data
        _LOGGER.debug(f"Selenium step data keys: {list(self.data.keys())}")
        if "selenium_status" in self.data:
            _LOGGER.debug(f"Selenium status: {self.data['selenium_status']}")
        else:
            _LOGGER.warning("No selenium_status in self.data")
            # Initialize it if missing
            self.data["selenium_status"] = {}

        # Get default selenium URL (first working one)
        selenium_url = next((url for url, status in self.data["selenium_status"].items() if status), 
                           self.data.get("web_driver", ""))
                           
        schema = build_selenium_schema(selenium_url)

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
        schema = build_advanced_schema(self.data)

        if user_input is not None:
            # Check if icon_color_mapping is valid JSON if provided
            if user_input.get("icon_color_mapping"):
                if not is_valid_json(user_input["icon_color_mapping"]):
                    errors["icon_color_mapping"] = "invalid_json"
                    _LOGGER.warning("Invalid JSON in icon_color_mapping field")
            
            if not errors:
                self.data.update(user_input)
                
                # Get council data for fallback values
                council_key = self.data.get("selected_council", "")
                council_data = self.data.get("council_list", {}).get(council_key, {})
                
                # If the user hasn't provided a URL, use the default from the council data
                if not self.data.get("url"):
                    _LOGGER.debug(f"URL is missing, attempting to use council's default URL")
                    default_url = council_data.get("url", "")
                    self.data["url"] = default_url
                    _LOGGER.debug(f"Using council's default URL: {default_url}")
                
                # If skip_get_url is missing, get it from council data
                if "skip_get_url" not in self.data:
                    skip_get_url = council_data.get("skip_get_url", False)
                    self.data["skip_get_url"] = skip_get_url
                    _LOGGER.debug(f"Using council's skip_get_url value: {skip_get_url}")
                
                # Define field mappings for parameter name corrections
                field_mappings = {
                    "headless_mode": "headless",  # headless_mode should be headless
                    "house_number": "number",     # house_number should be number
                }
                
                # List of essential fields with correct parameter names
                essential_fields = [
                    "name", 
                    "postcode", 
                    "uprn", 
                    "number",  
                    "usrn", 
                    "url", 
                    "original_parser",
                    "skip_get_url",
                    "web_driver", 
                    "headless",
                    "local_browser",
                    "manual_refresh_only", 
                    "update_interval", 
                    "timeout", 
                    "icon_color_mapping"
                ]
                
                # Create filtered data dictionary with correct parameter names
                filtered_data = {}
                for field in essential_fields:
                    # Check if this field has a mapping (old name → new name)
                    old_field = next((old for old, new in field_mappings.items() if new == field), field)
                    
                    # Get value using the old field name from self.data
                    value = self.data.get(old_field)
                    
                    # If value exists, add it to filtered_data with the correct field name
                    if value is not None:
                        filtered_data[field] = value
                
                # Save selected_council as council in the final config
                filtered_data["council"] = council_key
                
                # Final validation for critical fields
                if not filtered_data.get("council"):
                    _LOGGER.error("Council not specified in configuration")
                    errors["base"] = "missing_council"
                elif not filtered_data.get("url"):
                    _LOGGER.error("URL not specified in configuration")
                    errors["base"] = "missing_url"
                else:
                    _LOGGER.debug(f"Final configuration: {filtered_data}")
                    return self.async_create_entry(title=filtered_data["name"], data=filtered_data)

        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            errors=errors
        )
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return UkBinCollectionOptionsFlowHandler(config_entry)

