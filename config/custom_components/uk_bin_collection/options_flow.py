from typing import Dict, Any, Optional
import logging
from homeassistant import config_entries

from .utils import (
    is_valid_json,
    get_councils_json,
    build_options_schema,
    map_wiki_name_to_council_key,
)

_LOGGER = logging.getLogger(__name__)

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
        self.councils_data = await get_councils_json()
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
        schema = build_options_schema(
            existing_data,
            self.council_options,
            self.council_names
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"cancel": "Press Cancel to abort setup."},
        )