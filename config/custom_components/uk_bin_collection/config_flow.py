from homeassistant import config_entries
from .initialisation import initialisation_data
from .utils import (
    build_user_schema,
    build_council_schema,
    build_selenium_schema,
    build_advanced_schema
)

class BinCollectionConfigFlow(config_entries.ConfigFlow, domain="uk_bin_collection"):
    """Config flow for Bin Collection Data."""
    
    VERSION = 4
    
    def __init__(self):
        """Initialize the config flow."""
        self.data = {}

    async def async_step_user(self, user_input=None):
        """Step 1: Select Council."""
        await initialisation_data(self)

        errors = {}
        
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

        # This return statement was missing!
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

        selenium_url = next((url for url, status in self.data["selenium_status"].items() if status), "")
        schema = build_selenium_schema(selenium_url)

        if user_input is not None:
            self.data.update(user_input)
            if not user_input.get("web_driver") and not user_input.get("local_browser"):
                errors["base"] = "selenium_required"
            elif user_input.get("local_browser") and not self.data.get("chromium_installed", False):
                errors["base"] = "chromium_unavailable"
            else:
                return await self.async_step_advanced()

        return self.async_show_form(
            step_id="selenium",
            data_schema=schema,
            errors=errors
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