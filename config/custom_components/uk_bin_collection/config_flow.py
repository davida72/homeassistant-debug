from homeassistant import config_entries
from .initialisation import initialisation_data
import logging
from .utils import (
    build_user_schema,
    build_council_schema,
    build_selenium_schema,
    build_advanced_schema
)

_LOGGER = logging.getLogger(__name__)

class BinCollectionConfigFlow(config_entries.ConfigFlow, domain="uk_bin_collection"):
    """Config flow for Bin Collection Data."""
    
    VERSION = 4
    
    def __init__(self):
        """Initialize the config flow."""
        self.data = {}
        self._initialized = False

    async def async_step_user(self, user_input=None):
        """Step 1: Select Council."""
        
        errors = {}
        
        # Only run initialization once
        if not self._initialized:
            await initialisation_data(self)
            self._initialized = True
            _LOGGER.debug("Initialization completed")
        else:
            _LOGGER.debug("Using cached initialization data")

        
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
        
        schema = build_user_schema(
            wiki_names=wiki_names,
            default_name=default_name,
            default_council=detected_council_name
        )
        
        if user_input is not None:
            selected_wiki_name = user_input.get("selected_council")
            council_key = wiki_names_map.get(selected_wiki_name)
            
            # Update the data with both the display name and internal key
            self.data["name"] = user_input.get("name")
            self.data["selected_wiki_name"] = selected_wiki_name
            self.data["selected_council"] = council_key
            
            return await self.async_step_council_info()

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "detected_council": detected_council_name or "Not detected",
                "street_name": default_name or "Not found"
            }
        )

    async def async_step_council_info(self, user_input=None):
        """Step 2: Configure Council Information."""
        
        errors = {}
        
        if user_input is not None:
            self.data.update(user_input)
            return await self.async_step_selenium()

        council_key = self.data.get("selected_council", "")
        council_data = self.data.get("council_list", {}).get(council_key, {})
        wiki_command_url = council_data.get("wiki_command_url_override", "")

        default_values = {
            "postcode": self.data.get("detected_postcode", ""),
            "url": wiki_command_url
        }

        schema = build_council_schema(council_key, council_data, default_values)

        return self.async_show_form(
            step_id="council_info",
            data_schema=schema,
            errors=errors
        )

    async def async_step_selenium(self, user_input=None):
        """Step 3: Selenium configuration."""
        
        errors = {}

        # Check if Chromium is installed (only when needed later)
        from .utils import check_chromium_installed
        
        # Debug to see what's in self.data
        _LOGGER.debug(f"Selenium step data keys: {list(self.data.keys())}")
        if "selenium_status" in self.data:
            _LOGGER.debug(f"Selenium status: {self.data['selenium_status']}")
        else:
            _LOGGER.warning("No selenium_status in self.data")
            # Initialize it if missing
            self.data["selenium_status"] = {}

        # Get default selenium URL (first working one)
        selenium_url = next((url for url, status in self.data["selenium_status"].items() if status), "")
        schema = build_selenium_schema(selenium_url)

        if user_input is not None:
            self.data.update(user_input)
            
            # Get user selections
            use_local_browser = user_input.get("local_browser", False)
            web_driver_url = user_input.get("web_driver", "").strip()
            
            # Optimization: Only check what we need based on user choices
            if use_local_browser:
                # User selected local browser - check if Chromium is available
                chromium_installed = await check_chromium_installed()
                self.data["chromium_installed"] = chromium_installed
                
                if not chromium_installed:
                    errors["base"] = "chromium_unavailable"
                    _LOGGER.debug("Local browser selected but Chromium is not installed")
                else:
                    _LOGGER.debug("Local browser selected and Chromium is available")
                    # Local browser is available, we're good to go
            elif web_driver_url:
                # User provided a Selenium URL - check if it's accessible
                from .utils import check_selenium_server
                is_accessible = await check_selenium_server(web_driver_url)
                
                if not is_accessible:
                    errors["base"] = "selenium_url_unavailable"
                    _LOGGER.debug(f"Selected Selenium URL {web_driver_url} is NOT accessible")
                else:
                    _LOGGER.debug(f"Selected Selenium URL {web_driver_url} is accessible")
                    # Selenium URL is accessible, we're good to go
            else:
                # User didn't select either option
                errors["base"] = "no_selenium_method"
                _LOGGER.debug("No Selenium method selected (neither URL provided nor local browser enabled)")
            
            # If everything is valid, proceed to the next step
            if not errors:
                return await self.async_step_advanced()

        return self.async_show_form(
            step_id="selenium",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "chromium_status": "Available" if self.data.get("chromium_installed", False) else "Not checked"
            }
        )

    async def async_step_advanced(self, user_input=None):
        """Step 4: Advanced configuration."""
        errors = {}
        schema = build_advanced_schema()

        if user_input is not None:
            self.data.update(user_input)
            return self.async_create_entry(title=self.data["selected_council"], data=self.data)

        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            errors=errors
        )