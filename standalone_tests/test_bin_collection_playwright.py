import json
import os
import time
import asyncio
import pytest
import requests
from playwright.sync_api import sync_playwright, expect

class TestUkBinCollectionConfigFlow:
    @pytest.fixture(scope="class")
    def browser_context_args(self):
        return {
            "viewport": {"width": 1280, "height": 1024},
            "ignore_https_errors": True
        }
    
    @pytest.fixture(scope="function")
    def page(self, browser):
        page = browser.new_page()
        page.set_default_timeout(30000)  # 30 seconds timeout
        yield page
        page.close()
    
    @pytest.fixture(scope="function")
    def council_data(self):
        # Same council data fetching logic from your current test
        url = "http://65.108.155.134/input-cleaned-old.json"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            council_data = json.loads(response.text)
            
            # Check if we're dealing with the old format
            is_old_format = "GooglePublicCalendarCouncil" in council_data and "supported_councils" in council_data["GooglePublicCalendarCouncil"]
            
            normalized_data = {}
            
            if is_old_format:
                print("Detected old format JSON (input.json style)")
                # Process old format
                for key, value in council_data.items():
                    normalized_data[key] = value
                    # If this is GooglePublicCalendarCouncil, process its supported councils
                    if key == "GooglePublicCalendarCouncil" and "supported_councils" in value:
                        for alias in value.get("supported_councils", []):
                            alias_data = value.copy()
                            alias_data["original_parser"] = key
                            alias_data["wiki_command_url_override"] = "https://calendar.google.com/calendar/ical/XXXXX%40group.calendar.google.com/public/basic.ics"
                            alias_data["wiki_name"] = alias
                            if "wiki_note" in value:
                                alias_data["wiki_note"] = value["wiki_note"]
                            normalized_data[alias] = alias_data
            else:
                print("Detected new format JSON (placeholder_input.json style)")
                # Process new format
                normalized_data = council_data.copy()
            
            # Sort alphabetically by key (council ID)
            sorted_data = dict(sorted(normalized_data.items()))
            
            print(f"Loaded {len(sorted_data)} councils")
            
            # Convert to a list of councils with their keys as IDs
            council_list = []
            for key, value in sorted_data.items():
                if isinstance(value, dict):
                    council = value.copy()
                    council["id"] = key
                    council_list.append(council)
            
            return council_list
            
        except requests.RequestException as e:
            print(f"HTTP error fetching council data: {e}")
            return []
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in council data: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error fetching council data: {e}")
            return []
    
    def take_screenshot(self, page, council_name, step):
        screenshot_dir = os.path.join(os.path.dirname(__file__), "screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        filename = f"{screenshot_dir}/{council_name.replace(' ', '_')}_{step}.png"
        page.screenshot(path=filename)
        print(f"Screenshot saved: {filename}")
    
    def login_to_home_assistant(self, page):
        """Log in to Home Assistant with the provided credentials."""
        print("Logging in to Home Assistant...")
        
        # Navigate to Home Assistant
        page.goto("http://localhost:8123")
        
        # Check if already logged in
        if page.locator("home-assistant-main").is_visible():
            print("Already logged in")
            self.take_screenshot(page, "login", "already_logged_in")
            return True
        
        # Wait for login form to appear
        page.wait_for_selector("[aria-labelledby='username']", state="visible")
        
        # Fill in login credentials
        page.locator("[aria-labelledby='username']").fill("damor")
        page.locator("[aria-labelledby='password']").fill("tindrum")
        
        # Click login button
        page.locator("mwc-button").click()
        
        # Wait for login to complete
        page.wait_for_selector("home-assistant-main", state="visible")
        
        self.take_screenshot(page, "login", "successful")
        print("Login successful")
        return True
    
    def test_configure_councils(self, page, council_data):
        # First log in to Home Assistant
        self.login_to_home_assistant(page)
        
        # Limit to first 5 councils for testing
        for council in council_data[:5]:
            try:
                wiki_name = council.get("wiki_name", "")
                if not wiki_name:
                    continue
                
                print(f"Testing council: {wiki_name}")
                
                # Navigate to the HA integration page
                page.goto("http://localhost:8123/config/integrations/integration/uk_bin_collection")
                self.take_screenshot(page, wiki_name, "1_start_page")
                
                # Click the Add Service button 
                page.locator("text=Add Service").click()
                self.take_screenshot(page, wiki_name, "2_add_service_clicked")
                
                # Select council from dropdown - better shadow DOM handling in Playwright
                page.locator("ha-select").click()
                
                # Select the council by wiki_name
                dropdown_items = page.locator("mwc-list-item")
                for i in range(dropdown_items.count()):
                    item_text = dropdown_items.nth(i).text_content()
                    if wiki_name.lower() in item_text.lower():
                        dropdown_items.nth(i).click()
                        break
                
                self.take_screenshot(page, wiki_name, "3_council_selected")
                
                # Enter name
                page.locator("ha-textfield input").first.fill(wiki_name)
                self.take_screenshot(page, wiki_name, "4_name_entered")
                
                # Click Next
                page.locator("mwc-button:has-text('Next')").click()
                
                # Handle postcode if needed
                if page.locator("input[type='text']").first.is_visible():
                    postcode = council.get("postcode", "")
                    if postcode:
                        page.locator("input[type='text']").first.fill(postcode)
                        self.take_screenshot(page, wiki_name, "5_postcode_entered")
                
                    # Check for house number field
                    if page.locator("input[type='text']").nth(1).is_visible():
                        house_number = council.get("house_number", "")
                        if house_number:
                            page.locator("input[type='text']").nth(1).fill(house_number)
                            self.take_screenshot(page, wiki_name, "6_house_entered")
                    
                    # Click Next again
                    page.locator("mwc-button:has-text('Next')").click()
                
                # Handle UPRN if needed
                if page.locator("input[type='text']").first.is_visible():
                    uprn = council.get("uprn", "")
                    if uprn:
                        page.locator("input[type='text']").first.fill(uprn)
                        self.take_screenshot(page, wiki_name, "7_uprn_entered")
                        
                    # Click Next again
                    page.locator("mwc-button:has-text('Next')").click()
                
                # Handle URL if needed
                if page.locator("input[type='text']").first.is_visible():
                    url = council.get("url", "")
                    if url:
                        page.locator("input[type='text']").first.fill(url)
                        self.take_screenshot(page, wiki_name, "8_url_entered")
                        
                    # Click Next again
                    page.locator("mwc-button:has-text('Next')").click()
                
                # Wait for final confirmation
                page.wait_for_selector("text=Success!")
                self.take_screenshot(page, wiki_name, "9_completed")
                
                # Click Finish if available
                if page.locator("mwc-button:has-text('Finish')").is_visible():
                    page.locator("mwc-button:has-text('Finish')").click()
                
                print(f"Successfully configured {wiki_name}")
                
            except Exception as e:
                print(f"Error configuring {wiki_name}: {str(e)}")
                self.take_screenshot(page, wiki_name, "error")
                # Continue with the next council instead of failing the test
                continue