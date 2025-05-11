import aiohttp
import json
import logging

_LOGGER = logging.getLogger(__name__)

async def get_councils_json():
    """Fetch and return the supported councils data."""
    url = "https://raw.githubusercontent.com/robbrad/UKBinCollectionData/0.152.0/uk_bin_collection/tests/input.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data_text = await response.text()
                return json.loads(data_text)
    except Exception as e:
        _LOGGER.exception("Error fetching council data: %s", e)
        return {}

async def perform_selenium_checks(council_key, selenium_url=None):
    """Perform Selenium checks and return a formatted message."""
    # ...existing logic for Selenium checks...
    return selenium_message

async def check_chromium_installed():
    """Check if Chromium is installed."""
    # ...existing logic for Chromium checks...
    return chromium_installed