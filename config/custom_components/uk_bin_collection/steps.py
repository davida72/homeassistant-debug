from typing import Optional, Dict, Any
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from .property_info import async_get_property_info
import logging

_LOGGER = logging.getLogger(__name__) 

from .utils import (
    is_valid_json,
    get_councils_json,
    map_wiki_name_to_council_key,
    perform_selenium_checks,
    async_entry_exists
)

async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
    """Step 1: Basic info - name and council selection."""
    errors = {}

    if self.councils_data is None:
        self.councils_data = await get_councils_json()
        if not self.councils_data:
            _LOGGER.error("Council data is unavailable.")
            return self.async_abort(reason="Council Data Unavailable")

        self.council_names = list(self.councils_data.keys())
        self.council_options = [
            self.councils_data[name]["wiki_name"] for name in self.council_names
        ]
        _LOGGER.debug("Loaded council data: %s", self.council_names)
        
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
            description_placeholders["step1_description"] = f"Based on your location, we detected {detected_wiki_name}."
            _LOGGER.info("Pre-selecting detected council: %s", detected_wiki_name)
        except (KeyError, IndexError):
            _LOGGER.warning("Could not get wiki_name for detected council: %s", self.detected_council)
            description_placeholders["step1_description"] = f"Please [contact us](https://github.com/robbrad/UKBinCollectionData#requesting-your-council) if your council isn't listed"
    else:
        description_placeholders["step1_description"] = f"Please [contact us](https://github.com/robbrad/UKBinCollectionData#requesting-your-council) if your council isn't listed."

    return self.async_show_form(
        step_id="user",
        data_schema=vol.Schema(
            {
                vol.Required("name", default=default_name): cv.string,
                vol.Required("council", default=default_council): vol.In(self.council_options),
            }
        ),
        errors=errors,
        description_placeholders=description_placeholders,
    )

async def async_step_council_info(self, user_input=None):
    """Step 2: Council-specific information."""
    errors = {}
                
    council_key = self.data.get("council")
    council_info = self.councils_data.get(council_key, {})
    
    # Get wiki info if available - use consistent variable name
    wiki_note = council_info.get("wiki_note", "")
    _LOGGER.info("Wiki note for %s: '%s'", council_key, wiki_note)  # Log the actual value

    if user_input is not None:
        # If there are no errors, just save data and proceed
        self.data.update(user_input)
        if "web_driver" in council_info:
            return await self.async_step_selenium()
        else:
            return await self.async_step_advanced()
    
    # Build schema with council-specific fields
    schema_fields = {}
    
    # Set default values
    default_values = {}
    
    # If we have property info, use it to set defaults
    if hasattr(self, 'property_info') and self.property_info:
        # Set default postcode if available and required by council
        if "postcode" in council_info and self.property_info.get("postcode"):
            default_values["postcode"] = self.property_info["postcode"]
            _LOGGER.debug("Using property postcode as default: %s", default_values["postcode"])
    
    # Add fields based on council requirements
    if "wiki_command_url_override" in council_info:
        schema_fields[vol.Required("url", default=council_info.get("wiki_command_url_override", ""))] = cv.string
    if "uprn" in council_info:
        schema_fields[vol.Required("uprn")] = cv.string
    if "postcode" in council_info:
        default_postcode = default_values.get("postcode", "")
        schema_fields[vol.Required("postcode", default=default_postcode)] = cv.string
    if "house_number" in council_info:
        schema_fields[vol.Required("number")] = cv.string
    if "usrn" in council_info:
        schema_fields[vol.Required("usrn")] = cv.string
    
    # Always include a dummy field if no fields were added
    # This ensures the form is displayed with at least something on it
    if not schema_fields:
        schema_fields[vol.Optional("no_config_required", default=True)] = bool
        step2_description = "No additional configuration required for this council."
    else:
        if wiki_note: 
            step2_description = wiki_note
        else:
            step2_description = f"Please provide the required information for {council_info.get('wiki_name', council_key)}."

    schema = vol.Schema(schema_fields)
    
    # Set description placeholders
    description_placeholders = {
        "council_name": council_info.get("wiki_name", council_key),
        "step2_description": step2_description,
    }
    
    return self.async_show_form(
        step_id="council_info",
        data_schema=schema,
        errors=errors,
        description_placeholders=description_placeholders,
    )

async def async_step_selenium(self, user_input=None):
    """Step 3: Selenium configuration (if needed)."""
    errors = {}
        
    council_key = self.data.get("council")
    
    if user_input is not None:
            
        # Validate selenium inputs
        # Add validation logic here if needed
        
        if not errors:
            # Update self.data with selenium configuration
            self.data.update(user_input)
            return await self.async_step_advanced()
            
    # Perform selenium checks
    selenium_message, selenium_available, chromium_installed = await perform_selenium_checks(
        council_key,
        self.councils_data,
        self.data
    )
    self.selenium_available = selenium_available
    self.selenium_checked = True
    self.chromium_installed = chromium_installed

    # Build form
    schema = vol.Schema({
        vol.Optional("web_driver", default=""): cv.string,
        vol.Optional("headless", default=True): bool,
        vol.Optional("local_browser", default=False): bool,
    })
    
    description_placeholders = {
        "selenium_message": selenium_message,
    }
    
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
    
    # Build advanced schema
    schema = vol.Schema({
        vol.Optional("manual_refresh_only", default=True): bool,
        vol.Optional("update_interval", default=12): vol.All(
            cv.positive_int, vol.Range(min=1)
        ),
        vol.Optional("timeout", default=60): vol.All(
            vol.Coerce(int), vol.Range(min=10)
        ),
        vol.Optional("icon_color_mapping", default=""): cv.string,
    })        
    
    description_placeholders = {
        "advanced_description": "Configure advanced settings for your bin collection."
    }

    return self.async_show_form(
        step_id="advanced",
        data_schema=schema,
        errors=errors,
        description_placeholders=description_placeholders,
    )