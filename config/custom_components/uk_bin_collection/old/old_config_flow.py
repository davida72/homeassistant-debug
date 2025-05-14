import logging
from typing import Any, Dict, Optional  # Add Optional import

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .utils import (
    is_valid_json,
    get_councils_json,
    build_reconfigure_schema,
    map_wiki_name_to_council_key,
)

import collections

from .const import DOMAIN, LOG_PREFIX, SELENIUM_SERVER_URLS, BROWSER_BINARIES

_LOGGER = logging.getLogger(__name__)

from .steps import async_step_user, async_step_council_info, async_step_selenium, async_step_advanced
from .options_flow import UkBinCollectionOptionsFlowHandler

class UkBinCollectionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UkBinCollection."""

    VERSION = 3

    def __init__(self):
        self.councils_data = None
        self.data = {}
        self.council_names = []
        self.council_options = []
        self.selenium_checked = False
        self.selenium_available = False


    # step 1 - get name and council
    async def async_step_user(self, user_input=None):
        return await async_step_user(self, user_input)

    # step 2 - get council specific info
    async def async_step_council_info(self, user_input=None):
        return await async_step_council_info(self, user_input)

    # step 3 - get selenium info
    async def async_step_selenium(self, user_input=None):
        return await async_step_selenium(self, user_input)
    
    # step 4 - get advanced options
    async def async_step_advanced(self, user_input=None):
        return await async_step_advanced(self, user_input)
    
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
            self.councils_data = await get_councils_json()
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
            council_key = map_wiki_name_to_council_key(
                user_input["council"], 
                self.council_options, 
                self.council_names
            )
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
                if not is_valid_json(user_input["icon_color_mapping"]):
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
        schema = build_reconfigure_schema(
            existing_entry.data, 
            council_wiki_name, 
            self.council_options
        )

        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"selenium_message": ""},
        )

    async def async_step_import(
        self, import_config: Dict[str, Any]
    ) -> config_entries.FlowResult:
        """Handle import from configuration.yaml."""
        return await self.async_step_user(import_config)


async def async_get_options_flow(config_entry):
    """Get the options flow for this handler."""
    return UkBinCollectionOptionsFlowHandler(config_entry)