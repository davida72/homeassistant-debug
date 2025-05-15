"""Options flow handler for the UK Bin Collection integration."""
import logging
from homeassistant import config_entries

from .config_flow import BinCollectionConfigFlow
from .initialisation import initialisation_data

_LOGGER = logging.getLogger(__name__)

class UkBinCollectionOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for UkBinCollection by reusing config flow steps."""

    def __init__(self, config_entry):
        """Initialize options flow with existing config entry data."""
        self.config_entry = config_entry
        self.config_flow = None

    async def async_step_init(self, user_input=None):
        """Initialize the options flow and redirect to the first step."""
        # Initialize a new config flow instance
        self.config_flow = BinCollectionConfigFlow()
        
        # Set the hass property to use in initialisation
        self.config_flow.hass = self.hass
        
        # Pre-load the existing data to preserve it through all steps
        self.config_flow.data = dict(self.config_entry.data)
        
        # Keep track that we're in options flow mode
        self.config_flow.options_flow = True
        
        # Need to run initialization to get council data
        await initialisation_data(self.config_flow)
        
        _LOGGER.debug(
            "Options flow initialized with data: %s", 
            {k: v for k, v in self.config_flow.data.items() if k not in ["postcode", "uprn"]}
        )
        
        # Start with the user step
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """First step to select the council."""
        # Get the result from the config flow step
        result = await self.config_flow.async_step_user(user_input)
        
        # Process the result
        if result["type"] == "form":
            if user_input and not result.get("errors"):
                # Successfully completed this step, but form still returned
                # This means we need to move to the next step
                if result["step_id"] == "council_info":
                    return await self.async_step_council_info()
        
        # Return the result for any other case
        return result

    async def async_step_council_info(self, user_input=None):
        """Second step to configure council information."""
        # Get the result from the config flow step
        result = await self.config_flow.async_step_council_info(user_input)
        
        # Process the result
        if result["type"] == "form":
            if user_input and not result.get("errors"):
                # Successfully completed this step, move to next step
                if result["step_id"] == "selenium":
                    return await self.async_step_selenium()
                elif result["step_id"] == "advanced":
                    return await self.async_step_advanced()
        
        # Return the result for any other case
        return result

    async def async_step_selenium(self, user_input=None):
        """Third step to configure selenium options."""
        # Get the result from the config flow step
        result = await self.config_flow.async_step_selenium(user_input)
        
        # Process the result
        if result["type"] == "form":
            if user_input and not result.get("errors"):
                # Successfully completed this step, move to next step
                if result["step_id"] == "advanced":
                    return await self.async_step_advanced()
        
        # Return the result for any other case
        return result

    async def async_step_advanced(self, user_input=None):
        """Final step to configure advanced options."""
        # Get the result from the config flow step
        result = await self.config_flow.async_step_advanced(user_input)
        
        # Process the result
        if result["type"] == "create_entry":
            # Config flow created an entry, update the existing entry instead
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=self.config_flow.data,
            )
            
            # Reload the entry to apply changes
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            _LOGGER.info("Options updated and config entry reloaded.")
            
            # Return empty options data
            return self.async_create_entry(title="", data={})
        
        # Return the result for any other case
        return result