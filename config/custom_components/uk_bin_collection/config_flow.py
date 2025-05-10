import json
import logging
import shutil
import asyncio
from typing import Any, Dict, Optional

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

import collections  # At the top with other imports

from .const import DOMAIN, LOG_PREFIX, SELENIUM_SERVER_URLS, BROWSER_BINARIES

_LOGGER = logging.getLogger(__name__)


class UkBinCollectionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UkBinCollection."""

    VERSION = 3  # Incremented version for config flow changes

    def __init__(self):
        self.councils_data: Optional[Dict[str, Any]] = None
        self.data: Dict[str, Any] = {}
        self.council_names: list = []
        self.council_options: list = []
        self.selenium_checked: bool = False
        self.selenium_available: bool = False
        self.selenium_results: list = []
        self.chromium_checked: bool = False
        self.chromium_installed: bool = False

    async def async_migrate_entry(
        self, config_entry: config_entries.ConfigEntry
    ) -> bool:
        """Migrate old entry to the new version with manual refresh ticked."""
        _LOGGER.info("Migrating config entry from version %s", config_entry.version)
        data = dict(config_entry.data)

        if config_entry.version < 3:
            # If the manual_refresh_only key is not present, add it and set to True.
            if "manual_refresh_only" not in data:
                _LOGGER.info("Setting 'manual_refresh_only' to True in the migration")
                data["manual_refresh_only"] = True

            self.hass.config_entries.async_update_entry(config_entry, data=data)
            _LOGGER.info("Migration to version %s successful", self.VERSION)
        return True

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        """Step 1: Basic info - name and council selection."""
        errors = {}

        if self.councils_data is None:
            self.councils_data = await self.get_councils_json()
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
                            if council_data.get("LAD24CD") == lad_code:  # Changed from lad_code to LAD24CD
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
                existing_entry = await self._async_entry_exists(user_input)
                if existing_entry:
                    errors["base"] = "duplicate_entry"
                    _LOGGER.warning(
                        "Duplicate entry found: %s", existing_entry.data.get("name")
                    )

            if not errors:
                # Map selected wiki_name back to council key
                council_key = self.map_wiki_name_to_council_key(user_input["council"])
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
                description_placeholders["detected_council"] = f"Based on your location, we detected {detected_wiki_name}."
                _LOGGER.info("Pre-selecting detected council: %s", detected_wiki_name)
            except (KeyError, IndexError):
                _LOGGER.warning("Could not get wiki_name for detected council: %s", self.detected_council)
                description_placeholders["detected_council"] = ""
        else:
            description_placeholders["detected_council"] = ""

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
        
        if not hasattr(self, 'data') or not self.data.get("council"):
            # If we don't have data, go back to step 1
            return await self.async_step_user()
            
        council_key = self.data.get("council")
        council_info = self.councils_data.get(council_key, {})
        
        if user_input is not None:
            # If there are no errors, just save data and proceed
            self.data.update(user_input)
            if "web_driver" in council_info:
                return await self.async_step_selenium()
            else:
                return await self.async_step_advanced()
        
        # Build schema with council-specific fields
        schema_fields = {}
        
        # Add fields based on council requirements
        if not council_info.get("skip_get_url", False):
            schema_fields[vol.Required("url")] = cv.string
        if "uprn" in council_info:
            schema_fields[vol.Required("uprn")] = cv.string
        if "postcode" in council_info:
            schema_fields[vol.Required("postcode")] = cv.string
        if "house_number" in council_info:
            schema_fields[vol.Required("number")] = cv.string
        if "usrn" in council_info:
            schema_fields[vol.Required("usrn")] = cv.string
        
        # Always include a dummy field if no fields were added
        # This ensures the form is displayed with at least something on it
        if not schema_fields:
            schema_fields[vol.Optional("no_config_required", default=True)] = bool
            description_note = "No additional configuration required for this council."
        else:
            description_note = f"Please provide the required information for {council_info.get('wiki_name', council_key)}."

        schema = vol.Schema(schema_fields)
        
        # Set description placeholders
        description_placeholders = {
            "council_name": council_info.get("wiki_name", council_key),
            "description_note": description_note,
            "previous_step": "user"  # This enables the Back button
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
        
        if not hasattr(self, 'data') or not self.data.get("council"):
            # If we don't have data, go back to step 1
            return await self.async_step_user()
            
        council_key = self.data.get("council")
        
        if user_input is not None:
            # If this is a previous button request, go back
            if user_input.get("back", False):
                return await self.async_step_council_info()
                
            # Validate selenium inputs
            # Add validation logic here if needed
            
            if not errors:
                # Update self.data with selenium configuration
                self.data.update(user_input)
                return await self.async_step_advanced()
                
        # Perform selenium checks
        selenium_message = await self.perform_selenium_checks(council_key)
        
        # Build form
        schema = vol.Schema({
            vol.Optional("web_driver", default=""): cv.string,
            vol.Optional("headless", default=True): bool,
            vol.Optional("local_browser", default=False): bool,
        })
        
        description_placeholders = {
            "selenium_message": selenium_message,
            "previous_step": "council_info"  # Back button to council_info step
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
        
        if not hasattr(self, 'data') or not self.data.get("council"):
            # If we don't have data, go back to step 1
            return await self.async_step_user()
            
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
                if not self.is_valid_json(user_input["icon_color_mapping"]):
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
        
        # Determine previous step for the back button
        previous_step = "selenium" if requires_selenium else "council_info"
        
        description_placeholders = {
            "previous_step": previous_step  # Dynamic back button
        }
        
        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_council(self, user_input: Optional[Dict[str, Any]] = None):
        """Second step to configure the council details."""
        errors = {}
        council_key = self.data.get("council")
        council_info = self.councils_data.get(council_key, {})
        requires_selenium = "web_driver" in council_info

        if user_input is not None:
            _LOGGER.debug("Council step user input: %s", user_input)
            # Validate JSON mapping if provided
            if user_input.get("icon_color_mapping"):
                if not self.is_valid_json(user_input["icon_color_mapping"]):
                    if not self.is_valid_json(user_input["icon_color_mapping"]):
                        errors["icon_color_mapping"] = "Invalid JSON format."

            # Handle 'skip_get_url' if necessary
            if council_info.get("skip_get_url", False):
                user_input["skip_get_url"] = True
                user_input["url"] = council_info.get("url", "")

            # Merge user_input with existing data
            self.data.update(user_input)

            # If no errors, create the config entry
            if not errors:
                _LOGGER.info(
                    "%s Creating config entry with data: %s", LOG_PREFIX, self.data
                )
                return self.async_create_entry(title=self.data["name"], data=self.data)
            else:
                _LOGGER.debug("Errors in council step: %s", errors)

        # Prepare description placeholders
        description_placeholders = {}
        if requires_selenium:
            description = await self.perform_selenium_checks(council_key)
            description_placeholders["selenium_message"] = description
        else:
            description_placeholders["selenium_message"] = ""

        # Show the form
        return self.async_show_form(
            step_id="council",
            data_schema=await self.get_council_schema(council_key),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_reconfigure(self, user_input: Optional[Dict[str, Any]] = None):
        """Handle reconfiguration of the integration."""
        return await self.async_step_reconfigure_confirm()

    async def async_step_reconfigure_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ):
        """Handle a reconfiguration flow initialized by the user."""
        errors = {}
        existing_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if existing_entry is None:
            _LOGGER.error("Reconfiguration failed: Config entry not found.")
            return self.async_abort(reason="Reconfigure Failed")

        if self.councils_data is None:
            self.councils_data = await self.get_councils_json()
            self.council_names = list(self.councils_data.keys())
            self.council_options = [
                self.councils_data[name]["wiki_name"] for name in self.council_names
            ]
            _LOGGER.debug("Loaded council data for reconfiguration.")

        council_key = existing_entry.data.get("council")
        council_info = self.councils_data.get(council_key, {})
        council_wiki_name = council_info.get("wiki_name", "")

        if user_input is not None:
            _LOGGER.debug("Reconfigure user input: %s", user_input)
            # Map selected wiki_name back to council key
            council_key = self.map_wiki_name_to_council_key(user_input["council"])
            user_input["council"] = council_key

            # Validate update_interval
            update_interval = user_input.get("update_interval")
            if update_interval is not None:
                try:
                    update_interval = int(update_interval)
                    if update_interval < 1:
                        errors["update_interval"] = "Must be at least 1 hour."
                except ValueError:
                    errors["update_interval"] = "Invalid number."

            # Validate JSON mapping if provided
            if user_input.get("icon_color_mapping"):
                if not self.is_valid_json(user_input["icon_color_mapping"]):
                    errors["icon_color_mapping"] = "Invalid JSON format."

            if not errors:
                # Merge the user input with existing data
                data = {**existing_entry.data, **user_input}
                data["icon_color_mapping"] = user_input.get("icon_color_mapping", "")

                self.hass.config_entries.async_update_entry(
                    existing_entry,
                    title=user_input.get("name", existing_entry.title),
                    data=data,
                )
                # Trigger a data refresh by reloading the config entry
                await self.hass.config_entries.async_reload(existing_entry.entry_id)
                _LOGGER.info(
                    "Configuration updated for entry: %s", existing_entry.entry_id
                )
                return self.async_abort(reason="Reconfigure Successful")
            else:
                _LOGGER.debug("Errors in reconfiguration: %s", errors)

        # Build the schema with existing data
        schema = self.build_reconfigure_schema(existing_entry.data, council_wiki_name)

        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"selenium_message": ""},
        )

    async def get_councils_json(self) -> Dict[str, Any]:
        """Fetch and return the supported councils data, including aliases and sorted alphabetically."""
        url = "https://raw.githubusercontent.com/robbrad/UKBinCollectionData/0.152.0/uk_bin_collection/tests/input.json"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    data_text = await response.text()
                    original_data = json.loads(data_text)

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
            _LOGGER.exception("Error fetching council data: %s", e)
            return {}

    async def get_council_schema(self, council: str) -> vol.Schema:
        """Generate the form schema based on council requirements."""
        council_info = self.councils_data.get(council, {})
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
        self, existing_data: Dict[str, Any], council_wiki_name: str
    ) -> vol.Schema:
        """Build the schema for reconfiguration with existing data."""
        fields = {
            vol.Required("name", default=existing_data.get("name", "")): str,
            vol.Required("council", default=council_wiki_name): vol.In(
                self.council_options
            ),
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
                fields[vol.Optional(field_name, default=existing_data[field_name])] = (
                    validator
                )

        fields[
            vol.Optional(
                "icon_color_mapping",
                default=existing_data.get("icon_color_mapping", ""),
            )
        ] = str

        return vol.Schema(fields)

    async def perform_selenium_checks(self, council_key: str) -> str:
        """Perform Selenium and Chromium checks and return a formatted message."""
        messages = []
        council_info = self.councils_data.get(council_key, {})
        council_name = council_info.get("wiki_name", council_key)

        custom_selenium_url = self.data.get("selenium_url")
        selenium_results = await self.check_selenium_server(custom_selenium_url)
        self.selenium_available = any(accessible for _, accessible in selenium_results)
        self.selenium_checked = True

        self.chromium_installed = await self.check_chromium_installed()
        self.chromium_checked = True

        # Start building the message with formatted HTML
        messages.append(f"<b>{council_name}</b> requires Selenium to run.<br><br>")

        # Selenium server check results
        messages.append("<b>Remote Selenium server URLs checked:</b><br>")
        for url, accessible in selenium_results:
            status = "✅ Accessible" if accessible else "❌ Not accessible"
            messages.append(f"{url}: {status}<br>")

        # Chromium installation check
        chromium_status = (
            "✅ Installed" if self.chromium_installed else "❌ Not installed"
        )
        messages.append("<br><b>Local Chromium browser check:</b><br>")
        messages.append(f"Chromium browser is {chromium_status}.")

        # Combine messages
        return "".join(messages)

    async def check_selenium_server(self, custom_url: Optional[str] = None) -> list:
        """Check if Selenium servers are accessible."""
        urls = SELENIUM_SERVER_URLS.copy()
        if custom_url:
            urls.insert(0, custom_url)

        results = []
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, timeout=5) as response:
                        response.raise_for_status()
                        accessible = response.status == 200
                        results.append((url, accessible))
                        _LOGGER.debug("Selenium server %s is accessible.", url)
                except aiohttp.ClientError as e:
                    _LOGGER.warning(
                        "Failed to connect to Selenium server at %s: %s", url, e
                    )
                    results.append((url, False))
                except Exception as e:
                    _LOGGER.exception(
                        "Unexpected error checking Selenium server at %s: %s", url, e
                    )
                    results.append((url, False))
        return results

    async def check_chromium_installed(self) -> bool:
        """Check if Chromium is installed."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._sync_check_chromium)
        if result:
            _LOGGER.debug("Chromium is installed.")
        else:
            _LOGGER.warning("Chromium is not installed.")
        return result

    def _sync_check_chromium(self) -> bool:
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

    def map_wiki_name_to_council_key(self, wiki_name: str) -> str:
        """Map the council wiki name back to the council key."""
        try:
            index = self.council_options.index(wiki_name)
            council_key = self.council_names[index]
            _LOGGER.debug(
                "Mapped wiki name '%s' to council key '%s'.", wiki_name, council_key
            )
            return council_key
        except ValueError:
            _LOGGER.error("Wiki name '%s' not found in council options.", wiki_name)
            return ""

    @staticmethod
    def is_valid_json(json_str: str) -> bool:
        """Validate if a string is valid JSON."""
        try:
            json.loads(json_str)
            return True
        except json.JSONDecodeError as e:
            _LOGGER.debug("JSON decode error: %s", e)
            return False

    async def _async_entry_exists(
        self, user_input: Dict[str, Any]
    ) -> Optional[config_entries.ConfigEntry]:
        """Check if a config entry with the same name or data already exists."""
        for entry in self._async_current_entries():
            if entry.data.get("name") == user_input.get("name"):
                return entry
            if entry.data.get("council") == user_input.get(
                "council"
            ) and entry.data.get("url") == user_input.get("url"):
                return entry
        return None

    async def async_step_import(
        self, import_config: Dict[str, Any]
    ) -> config_entries.FlowResult:
        """Handle import from configuration.yaml."""
        return await self.async_step_user(import_config)

    def _build_council_info_schema(self, council_key):
        """Build schema for council-specific information."""
        council_info = self.councils_data.get(council_key, {})
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


class UkBinCollectionOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for UkBinCollection."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self.councils_data: Optional[Dict[str, Any]] = None
        self.council_names: list = []
        self.council_options: list = []

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        existing_data = self.config_entry.data

        # Fetch council data
        self.councils_data = await self.get_councils_json()
        if not self.councils_data:
            _LOGGER.error("Council data is unavailable for options flow.")
            return self.async_abort(reason="Council Data Unavailable")

        self.council_names = list(self.councils_data.keys())
        self.council_options = [
            self.councils_data[name]["wiki_name"] for name in self.council_names
        ]
        _LOGGER.debug("Loaded council data for options flow.")

        if user_input is not None:
            _LOGGER.debug("Options flow user input: %s", user_input)
            # Map selected wiki_name back to council key
            council_key = self.map_wiki_name_to_council_key(user_input["council"])
            user_input["council"] = council_key

            # Validate update_interval
            update_interval = user_input.get("update_interval")
            if update_interval is not None:
                try:
                    update_interval = int(update_interval)
                    if update_interval < 1:
                        errors["update_interval"] = "Must be at least 1 hour."
                except ValueError:
                    errors["update_interval"] = "Invalid number."

            # Validate JSON mapping if provided
            if user_input.get("icon_color_mapping"):
                if not UkBinCollectionConfigFlow.is_valid_json(
                    user_input["icon_color_mapping"]
                ):
                    errors["icon_color_mapping"] = "Invalid JSON format."

            if user_input.get("manual_refresh_only"):
                user_input["update_interval"] = None

            if not errors:
                # Merge the user input with existing data
                data = {**existing_data, **user_input}
                data["icon_color_mapping"] = user_input.get("icon_color_mapping", "")

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=data,
                )
                # Trigger a data refresh by reloading the config entry
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                _LOGGER.info("Options updated and config entry reloaded.")
                return self.async_create_entry(title="", data={})
            else:
                _LOGGER.debug("Errors in options flow: %s", errors)

        # Build the form with existing data
        schema = self.build_options_schema(existing_data)

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"cancel": "Press Cancel to abort setup."},
        )

    async def get_councils_json(self) -> Dict[str, Any]:
        """Fetch and return the supported councils data."""
        url = "https://raw.githubusercontent.com/robbrad/UKBinCollectionData/0.111.0/uk_bin_collection/tests/input.json"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    data_text = await response.text()
                    return json.loads(data_text)
        except aiohttp.ClientError as e:
            _LOGGER.error(
                "HTTP error while fetching council data for options flow: %s", e
            )
        except json.JSONDecodeError as e:
            _LOGGER.error("Error decoding council data JSON for options flow: %s", e)
        except Exception as e:
            _LOGGER.exception(
                "Unexpected error while fetching council data for options flow: %s", e
            )
        return {}

    def build_options_schema(self, existing_data: Dict[str, Any]) -> vol.Schema:
        """Build the schema for the options flow with existing data."""
        council_current_key = existing_data.get("council", "")
        try:
            council_current_wiki = self.council_options[
                self.council_names.index(council_current_key)
            ]
        except (ValueError, IndexError):
            council_current_wiki = ""

        fields = {
            vol.Required("name", default=existing_data.get("name", "")): str,
            vol.Required("council", default=council_current_wiki): vol.In(
                self.council_options
            ),
            vol.Optional("manual_refresh_only", default=False): bool,
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
                fields[vol.Optional(field_name, default=existing_data[field_name])] = (
                    validator
                )

        return vol.Schema(fields)

    def map_wiki_name_to_council_key(self, wiki_name: str) -> str:
        """Map the council wiki name back to the council key."""
        try:
            index = self.council_options.index(wiki_name)
            council_key = self.council_names[index]
            _LOGGER.debug(
                "Mapped wiki name '%s' to council key '%s'.", wiki_name, council_key
            )
            return council_key
        except ValueError:
            _LOGGER.error("Wiki name '%s' not found in council options.", wiki_name)
            return ""

    @staticmethod
    def is_valid_json(json_str: str) -> bool:
        """Validate if a string is valid JSON."""
        try:
            json.loads(json_str)
            return True
        except json.JSONDecodeError as e:
            _LOGGER.debug("JSON decode error in options flow: %s", e)
            return False


async def async_get_options_flow(config_entry):
    """Get the options flow for this handler."""
    return UkBinCollectionOptionsFlowHandler(config_entry)


# Property information retrieval functions
import requests
import base64

key_b64 = "QUl6YVN5QkRMVUxUN0VJbE50SGVyc3dQdGZtTDE1VHQzT2MwYlY4"
API_KEY = base64.b64decode(key_b64).decode("utf-8")


async def async_get_property_info(lat, lng):
    """
    Async version of get_property_info that uses aiohttp instead of requests.
    Given latitude and longitude, returns a dict with:
    - LAD24CD code (string) from postcodes.io
    - Postcode (string) from Google Geocode
    - Street Name (string) from Google Geocode
    """
    # 1. Get address info from Google Geocode API
    google_url = (
        f"https://maps.googleapis.com/maps/api/geocode/json"
        f"?latlng={lat},{lng}&result_type=street_address&key={API_KEY}"
    )
    
    async with aiohttp.ClientSession() as session:
        async with session.get(google_url) as google_resp:
            google_data = await google_resp.json()
            
    if not google_data.get("results"):
        _LOGGER.error("No results from Google Geocode API")
        raise ValueError("No results from Google Geocode API")
        
    address_components = google_data["results"][0]["address_components"]

    # Extract postcode and street name
    postcode = None
    street_name = None
    postal_town = None
    for comp in address_components:
        if "postal_code" in comp["types"]:
            postcode = comp["long_name"].replace(" ", "").lower()  # for postcodes.io
            postcode_for_output = comp["long_name"]  # for output
        if "route" in comp["types"]:
            street_name = comp["long_name"]
        if "postal_town" in comp["types"]:
            postal_town = comp["long_name"]
            
    if not postcode or not street_name:
        _LOGGER.error("Could not find postcode or street name in Google response")
        raise ValueError("Could not find postcode or street name in Google response")

    # 2. Get LAD24CD code from postcodes.io
    postcodes_url = f"https://api.postcodes.io/postcodes/{postcode}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(postcodes_url) as postcodes_resp:
            postcodes_data = await postcodes_resp.json()
            
    if postcodes_data["status"] != 200 or not postcodes_data.get("result"):
        _LOGGER.error("No results from postcodes.io")
        raise ValueError("No results from postcodes.io")
        
    lad24cd = postcodes_data["result"]["codes"]["admin_district"]
    admin_ward = postcodes_data["result"].get("admin_ward", "")

    _LOGGER.debug(
        "Retrieved property info - Street: %s, Ward: %s, Postcode: %s, LAD24CD: %s, Town: %s",
        street_name, admin_ward, postcode_for_output, lad24cd, postal_town or ""
    )

    return {
        "street_name": street_name,
        "admin_ward": admin_ward,
        "postcode": postcode_for_output,
        "LAD24CD": lad24cd,
        "postal_town": postal_town or ""  # Return empty string if postal_town not found
    }


def get_property_info(lat, lng):
    """
    Synchronous version - Given latitude and longitude, returns a dict with:
    - LAD24CD code (string) from postcodes.io
    - Postcode (string) from Google Geocode
    - Street Name (string) from Google Geocode
    """
    # 1. Get address info from Google Geocode API
    google_url = (
        f"https://maps.googleapis.com/maps/api/geocode/json"
        f"?latlng={lat},{lng}&result_type=street_address&key={API_KEY}"
    )
    google_resp = requests.get(google_url)
    google_data = google_resp.json()
    if not google_data.get("results"):
        raise ValueError("No results from Google Geocode API")
    address_components = google_data["results"][0]["address_components"]

    # Extract postcode and street name
    postcode = None
    street_name = None
    postal_town = None
    for comp in address_components:
        if "postal_code" in comp["types"]:
            postcode = comp["long_name"].replace(" ", "").lower()  # for postcodes.io
            postcode_for_output = comp["long_name"]  # for output
        if "route" in comp["types"]:
            street_name = comp["long_name"]
        if "postal_town" in comp["types"]:
            postal_town = comp["long_name"]
    if not postcode or not street_name:
        raise ValueError("Could not find postcode or street name in Google response")

    # 2. Get LAD24CD code from postcodes.io
    postcodes_url = f"https://api.postcodes.io/postcodes/{postcode}"
    postcodes_resp = requests.get(postcodes_url)
    postcodes_data = postcodes_resp.json()
    if postcodes_data["status"] != 200 or not postcodes_data.get("result"):
        raise ValueError("No results from postcodes.io")
    lad24cd = postcodes_data["result"]["codes"]["admin_district"]
    admin_ward = postcodes_data["result"].get("admin_ward", "")

    return {
        "street_name": street_name,
        "admin_ward": admin_ward,
        "postcode": postcode_for_output,
        "LAD24CD": lad24cd,
        "postal_town": postal_town or ""  # Return empty string if postal_town not found
    }


if __name__ == "__main__":
    import sys
    import asyncio
    from pprint import pprint
    
    async def main():
        if len(sys.argv) != 3:
            print("Usage: python config_flow.py <latitude> <longitude>")
            print("Example: python config_flow.py 50.831293 -0.157726")
            sys.exit(1)
        
        try:
            # Remove any commas from the input coordinates
            lat = float(sys.argv[1].replace(',', ''))
            lng = float(sys.argv[2].replace(',', ''))
            info = await async_get_property_info(lat, lng)
            pprint(info)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    if len(sys.argv) > 1:  # Only run if arguments are provided
        asyncio.run(main())
