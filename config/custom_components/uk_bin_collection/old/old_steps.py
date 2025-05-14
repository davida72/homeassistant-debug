from typing import Optional, Dict, Any
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from .property_info import async_get_property_info
import logging

from .const import SELENIUM_SERVER_URLS

_LOGGER = logging.getLogger(__name__) 

from .utils import (
    is_valid_json,
    get_councils_json,
    map_wiki_name_to_council_key,
    check_selenium_server,
    async_entry_exists,
    check_chromium_installed,
    build_user_schema,
    build_council_schema,
    build_selenium_schema,
    build_advanced_schema
)

async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
    """Step 1: Basic info - name and council selection."""
    errors = {}

    if self.councils_data is None:
        
        # Load council data from the JSON file
        self.councils_data = await get_councils_json("https://raw.githubusercontent.com/robbrad/UKBinCollectionData/0.152.0/uk_bin_collection/tests/input.json")
        if not self.councils_data:
            _LOGGER.error("Council data is unavailable.")
            return self.async_abort(reason="Council Data Unavailable")

        self.council_names = list(self.councils_data.keys())
        self.council_options = [
            self.councils_data[name]["wiki_name"] for name in self.council_names
        ]
        _LOGGER.debug("Loaded %d councils, options: %s", len(self.council_names), self.council_options[:5])
        
        # Get property info from the Home Assistant location
        try:
            # Check if latitude and longitude are available and valid
            lat = self.hass.config.latitude
            lng = self.hass.config.longitude

            if (lat is None or lng is None or lat == 0.0 and lng == 0.0):
                _LOGGER.warning("Home Assistant location not configured, skipping property info retrieval")
                self.property_info = None
            else:
                _LOGGER.debug("Retrieving property info for location: %f, %f", lat, lng)
                property_info = await async_get_property_info(lat, lng)
                self.property_info = property_info
                
                # Look up the council in our data based on the LAD24CD code
                lad_code = property_info.get("LAD24CD")
                if lad_code:
                    _LOGGER.debug("Found LAD code: %s", lad_code)
                    # Look for matching council using the LAD code
                    matching_council = None
                    for council_key, council_data in self.councils_data.items():
                        if council_data.get("LAD24CD") == lad_code:
                            matching_council = council_key
                            _LOGGER.info("Found matching council: %s for LAD code: %s", 
                                        council_data.get("wiki_name"), lad_code)
                            break
                        
                    if matching_council:
                        self.detected_council = matching_council
                    else:
                        _LOGGER.debug("No council match found for LAD code: %s", lad_code)
                        
        except Exception as e:
            _LOGGER.warning("Could not retrieve property info: %s", e)
            self.property_info = None

    if user_input is not None:
        _LOGGER.debug("User input received: %s", user_input)
        # Validate user input
        if not user_input.get("name"):
            errors["name"] = "name"
        if not user_input.get("council"):
            errors["council"] = "council"

        # Check for duplicate entries
        if not errors:
            existing_entry = await async_entry_exists(self, user_input)
            if existing_entry:
                errors["base"] = "duplicate_entry"
                _LOGGER.warning(
                    "Duplicate entry found: %s", existing_entry.data.get("name")
                )

        if not errors:
            # Map selected wiki_name back to council key
            council_key = map_wiki_name_to_council_key(
                user_input["council"],
                self.council_options,
                self.council_names
            )
            if not council_key:
                errors["council"] = "Invalid council selected."
                return self.async_show_form(
                    step_id="user", 
                    data_schema=vol.Schema({
                        vol.Required("name", default=default_name): cv.string,
                        vol.Required("council", default=default_council): vol.In(self.council_options),
                    }),
                    errors=errors,
                    description_placeholders=description_placeholders
                )
            
            # Store the council key in user_input
            user_input["council"] = council_key

            # Add original_parser if it's an alias
            if "original_parser" in self.councils_data[council_key]:
                user_input["original_parser"] = self.councils_data[council_key][
                    "original_parser"
                ]
            
            # Initialize self.data if it doesn't exist
            if not hasattr(self, 'data'):
                self.data = {}
                
            # Store user input in self.data
            self.data.update(user_input)
            _LOGGER.debug("User input after mapping: %s", self.data)

            # Proceed to the council_info step
            return await self.async_step_council_info()

    # Show the initial form
    default_council = None
    default_name = ""
    description_placeholders = {"cancel": "Press Cancel to abort setup."}
    
    # If we have property info, use it to set defaults
    if hasattr(self, 'property_info') and self.property_info:
        # Set default name to street name if available
        if self.property_info.get("street_name"):
            default_name = self.property_info["street_name"]
            _LOGGER.debug("Using street name as default name: %s", default_name)
    
    # If we have a detected council, pre-select it in the dropdown
    if hasattr(self, 'detected_council') and self.detected_council:
        try:
            detected_wiki_name = self.councils_data[self.detected_council]["wiki_name"]
            default_council = detected_wiki_name
            description_placeholders["step_user_description"] = f"Based on your location, we detected {detected_wiki_name}."
            _LOGGER.info("Pre-selecting detected council: %s", detected_wiki_name)
        except (KeyError, IndexError):
            _LOGGER.warning("Could not get wiki_name for detected council: %s", self.detected_council)
            description_placeholders["step_user_description"] = f"Please [contact us](https://github.com/robbrad/UKBinCollectionData#requesting-your-council) if your council isn't listed"
    else:
        description_placeholders["step_user_description"] = f"Please [contact us](https://github.com/robbrad/UKBinCollectionData#requesting-your-council) if your council isn't listed."

    # Use the schema building function from utils
    schema = build_user_schema(
        council_options=self.council_options, 
        default_council=default_council, 
        default_name=default_name
    )

    return self.async_show_form(
        step_id="user",
        data_schema=schema,
        errors=errors,
        description_placeholders=description_placeholders,
    )

async def async_step_council_info(self, user_input=None):
    """Step 2: Council-specific information."""
    errors = {}
                
    council_key = self.data.get("council")
    council_info = self.councils_data.get(council_key, {})
    wiki_name = council_info.get("wiki_name", "Unknown Council")
    self.data["wiki_name"] = wiki_name
    _LOGGER.info("Wiki note for %s: '%s'", council_key, wiki_name)

    if user_input is not None:
        # If there are no errors, just save data and proceed
        self.data.update(user_input)
        if "web_driver" in council_info:
            return await self.async_step_selenium()
        else:
            return await self.async_step_advanced()
    
    # Prepare default values
    default_values = {}
    
    # Check if the council has a URL override and should show the URL field
    if council_info.get("wiki_command_url_override"):
        default_values["url"] = council_info.get("wiki_command_url_override")
        _LOGGER.debug("Using default URL from wiki_command_url_override: %s", default_values["url"])
    
    # Then, add default values from property_info if available
    if hasattr(self, 'property_info') and self.property_info:
        # Map property info to default values
        property_mapping = {
            "postcode": "postcode",
            # Add other mappings as needed
        }
        
        for form_field, property_field in property_mapping.items():
            if property_field in self.property_info:
                default_values[form_field] = self.property_info[property_field]
                _LOGGER.debug("Using default %s = %s from property_info", form_field, default_values[form_field])
    
    # Debug log all default values to see what's being sent to the schema builder
    _LOGGER.info("Default values for council info form: %s", default_values)
    
    # Get schema fields with defaults applied
    schema_fields = build_council_schema(council_key, self.councils_data, default_values)
    
    # Initialize step description
    if not schema_fields:
        schema_fields[vol.Optional("no_config_required", default=True)] = bool
        step_council_info_description = "No additional configuration required for this council."
    else:
        wiki_note = council_info.get("wiki_note", "")
        step_council_info_description = f"{wiki_note}"
    
    # Create the schema
    schema = vol.Schema(schema_fields)
    
    # Set description placeholders
    description_placeholders = {
        "council_name": wiki_name,
        "step_council_info_description": step_council_info_description,
    }
    
    _LOGGER.debug("Council info schema with defaults: %s", schema_fields)
    
    return self.async_show_form(
        step_id="council_info",
        data_schema=schema,
        errors=errors,
        description_placeholders=description_placeholders,
    )

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

async def async_step_selenium(self, user_input=None):
    """Step 3: Selenium configuration (if needed)."""
    errors = {}

    # Add a message about Selenium requirement
    wiki_name = self.data.get("wiki_name", "Unknown Council")

    # Check if Selenium servers in the list are accessible
    urls = SELENIUM_SERVER_URLS.copy()
    selenium_results = []
    for url in urls:
        result = await check_selenium_server(url)
        selenium_results.append(result)

    # Determine if any Selenium server is accessible
    selenium_url = None
    for url, accessible in selenium_results:
        if accessible:
            selenium_url = url
            _LOGGER.debug("Found accessible Selenium server: %s", selenium_url)
            break

    # If selenium_url is still None after checking, set it to empty string
    if selenium_url is None:
        selenium_url = ""
        _LOGGER.debug("No accessible Selenium server found, using empty string")

    # Log what URL we'll use as default
    _LOGGER.info("Setting default Selenium URL to: '%s'", selenium_url)

    # Determine if Chromium is accessible
    chromium_installed = await check_chromium_installed()

    # If user input is provided, validate and update self.data
    if user_input:
        # Map the multi-select back to booleans
        user_input["headless"] = "Headless Mode" in user_input["selenium_options"]
        user_input["local_browser"] = "Use Local Browser" in user_input["selenium_options"]
        
        # Remove the temporary multi-select key
        del user_input["selenium_options"]
        
        # Validate Selenium access before proceeding to next step
        has_valid_selenium = False
        
        # Check if using local browser and Chromium is installed
        if user_input["local_browser"]:
            if chromium_installed:
                has_valid_selenium = True
                _LOGGER.info("Using local Chromium browser")
            else:
                errors["base"] = "chromium_unavailable"
                _LOGGER.error("Local Chromium browser selected but not installed")
        else:
            # Check if the user-provided Selenium URL is accessible
            user_selenium_url = user_input.get("web_driver", "")
            if user_selenium_url.strip():
                # Test the provided Selenium URL
                result = await check_selenium_server(user_selenium_url)
                if result[1]:  # If accessible
                    has_valid_selenium = True
                    _LOGGER.info("User-provided Selenium server is accessible")
                else:
                    errors["base"] = "selenium_unavailable"
                    _LOGGER.error(f"Provided Selenium URL {user_selenium_url} is not accessible")
            else:
                errors["base"] = "no_selenium_method"
                _LOGGER.error("No Selenium method selected (neither URL provided nor local browser enabled)")
        
        # If validation passed, update data and proceed to next step
        if not errors:
            # Update self.data with user input
            self.data.update(user_input)
            return await self.async_step_advanced()

    # Use the schema building function from utils with explicitly defined URL
    schema = build_selenium_schema(selenium_url=selenium_url, default_options=["Headless Mode"])
    
    # Description placeholder
    description_placeholders = {
        "step_selenium_description": (
            f"<b>{wiki_name}</b> requires "
            f"<a href='https://github.com/robbrad/UKBinCollectionData?tab=readme-ov-file#selenium' target='_blank'>Selenium</a> or Chromium to run."
        )
    }
 
    # Show the form
    return self.async_show_form(
        step_id="selenium",
        data_schema=schema,
        errors=errors,
        description_placeholders=description_placeholders,
    )

async def async_step_advanced(self, user_input=None):
    """Step 4: Advanced configuration."""
    errors = {}
        
    council_key = self.data.get("council")
    requires_selenium = "web_driver" in self.councils_data.get(council_key, {})
    
    if user_input is not None:
        # If this is a previous button request, go back
        if user_input.get("back", False):
            if requires_selenium:
                return await self.async_step_selenium()
            else:
                return await self.async_step_council_info()
                
        # Validate JSON mapping if provided
        if user_input.get("icon_color_mapping"):
            if not is_valid_json(user_input["icon_color_mapping"]):
                errors["icon_color_mapping"] = "invalid_json"
                
        if not errors:
            # Update self.data with advanced settings
            self.data.update(user_input)
            
            # Create the config entry with all collected data
            _LOGGER.info("Creating config entry with data: %s", self.data)
            return self.async_create_entry(title=self.data["name"], data=self.data)
    
    # Use the schema building function from utils
    schema = build_advanced_schema()

    description_placeholders = {
        "advanced_description": "Configure advanced settings for your bin collection."
    }

    return self.async_show_form(
        step_id="advanced",
        data_schema=schema,
        errors=errors,
        description_placeholders=description_placeholders,
    )
