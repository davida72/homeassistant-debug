import asyncio
from .utils import get_councils_json, check_selenium_server, check_chromium_installed
from .property_info import async_get_property_info
from .const import COUNCIL_DATA_URL
import logging

_LOGGER = logging.getLogger(__name__)

async def initialisation_data(self):
    """Initialise council data, property info, and selenium status."""
    
    # Fetch all councils and cache in self.data
    try:
        self.data["council_list"] = await get_councils_json(COUNCIL_DATA_URL)
    except ValueError as e:
        _LOGGER.error(f"Failed to fetch council data: {e}")
        return self.async_abort(reason="council_data_unavailable")
    
    # Fetch property info using Home Assistant's configured coordinates
    try:
        # Get coordinates from Home Assistant configuration
        if hasattr(self, 'hass') and self.hass is not None:
            system_options = {}
            try:
                system_options = self.hass.config.system_options.as_dict()
            except (AttributeError, KeyError):
                pass
                
            latitude = self.hass.config.latitude
            longitude = self.hass.config.longitude
            
            _LOGGER.debug("Fetching property info for coordinates: (%s, %s)", latitude, longitude)
            property_info = await async_get_property_info(latitude, longitude)
            self.data["property_info"] = property_info

            # Attempt to auto-detect the council based on LAD24CD
            lad_code = property_info.get("LAD24CD")
            if lad_code:
                for council_key, council_data in self.data["council_list"].items():
                    if council_data.get("LAD24CD") == lad_code:
                        self.data["detected_council"] = council_key
                        self.data["detected_postcode"] = property_info.get("postcode")
                        _LOGGER.info(f"Detected council: {council_data['wiki_name']} for LAD24CD: {lad_code}")
                        break
        else:
            _LOGGER.warning("Home Assistant instance not available, cannot fetch property info")
            self.data["property_info"] = None

    except Exception as e:
        _LOGGER.error(f"Error during property info fetch: {e}")
        self.data["property_info"] = None

    # Pre-check Selenium Servers
    urls = self.data.get("SELENIUM_SERVER_URLS", [])
    selenium_status = {url: await check_selenium_server(url) for url in urls}
    self.data["selenium_status"] = selenium_status