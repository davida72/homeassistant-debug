# Takes a latitude and longitude and returns property information

import aiohttp
import base64
import logging

_LOGGER = logging.getLogger(__name__) 

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
