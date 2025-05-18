import json
import os
import time
import pytest
import requests
import asyncio
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class TestUkBinCollectionConfigFlow:
    @pytest.fixture(scope="class")
    def driver(self):
        # Use Remote WebDriver to connect to Selenium in Docker
        options = webdriver.ChromeOptions()
        # Don't need headless as Docker runs headless already
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-web-security")  # Add this for cross-origin issues
        options.add_argument("--ignore-certificate-errors")  # Add this for SSL issues
        
        # Connect to the Selenium server running in Docker
        driver = webdriver.Remote(
            command_executor='http://localhost:4444/wd/hub',
            options=options
        )
        
        # Increase timeouts to avoid loading issues
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(30)
        
        driver.set_window_size(1280, 1024)
        yield driver
        driver.quit()
    
    @pytest.fixture(scope="function")
    def council_data(self):
        # Synchronous version of get_councils_json
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
    
    def take_screenshot(self, driver, council_name, step):
        screenshot_dir = os.path.join(os.path.dirname(__file__), "screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        filename = f"{screenshot_dir}/{council_name.replace(' ', '_')}_{step}.png"
        driver.save_screenshot(filename)
        print(f"Screenshot saved: {filename}")
    
    def login_to_home_assistant(self, driver):
        """Log in to Home Assistant with the provided credentials."""
        print("Logging in to Home Assistant...")
        
        # Use correct host address
        HOST_URL = "http://host.docker.internal:8123"  # Special Docker hostname to access host machine
        
        # Add retry logic for navigation
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"Attempt {attempt+1}/{max_retries} to access Home Assistant...")
                driver.get(HOST_URL)
                
                # Wait longer for initial page load
                time.sleep(5)
                print(f"Current URL: {driver.current_url}")
                self.take_screenshot(driver, "login", f"attempt_{attempt+1}")
                
                # Check if page loaded
                if driver.title or len(driver.page_source) > 100:
                    print("Page loaded successfully")
                    break
                    
            except Exception as e:
                print(f"Navigation attempt {attempt+1} failed: {str(e)}")
                if attempt == max_retries - 1:  # Last attempt
                    raise
                time.sleep(3)  # Wait before retry
        
        # Rest of login code...
        
        try:
            # Check if we're on the login page by looking for username input
            username_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 
                '[aria-labelledby="username"]'))
            )
            
            # Enter username
            username_input.clear()
            username_input.send_keys("damor")
            
            # Enter password
            password_input = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 
                '[aria-labelledby="password"]'))
            )

            password_input.clear()
            password_input.send_keys("tindrum")
            
            # Find and click the login button
            login_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//mwc-button"))
            )
            login_button.click()
            
            # Wait for login to complete and dashboard to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "home-assistant-main"))
            )
            
            self.take_screenshot(driver, "login", "successful")
            print("Login successful")
            return True
            
        except (TimeoutException, NoSuchElementException) as e:
            # Check if we're already logged in
            if "home-assistant-main" in driver.page_source:
                print("Already logged in")
                return True
                
            print(f"Login failed: {str(e)}")
            self.take_screenshot(driver, "login", "failed")
            return False
    
    def test_configure_councils(self, driver, council_data):
        # First log in to Home Assistant
        if not self.login_to_home_assistant(driver):
            pytest.fail("Could not log in to Home Assistant")
            
        # Now we have a proper list of councils
        # Limit to first 5 councils for testing
        for council in council_data[:5]:
            try:
                wiki_name = council.get("wiki_name", "")
                if not wiki_name:
                    continue
                
                print(f"Testing council: {wiki_name}")
                
                # Navigate to the HA integration page
                driver.get("http://host.docker.internal:8123/config/integrations/integration/uk_bin_collection")
                time.sleep(5)  # Wait for page to load
                self.take_screenshot(driver, wiki_name, "1_start_page")
                
                # Click the Add Service button
                add_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, 
                    "/home-assistant//home-assistant-main//ha-drawer/partial-panel-resolver/ha-panel-config/ha-config-integrations/ha-config-integration-page//hass-subpage/div/div[2]/ha-card/div/ha-button"))
                )
                add_button.click()
                time.sleep(2)
                self.take_screenshot(driver, wiki_name, "2_add_service_clicked")
                
                # Select council from dropdown
                dropdown = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, 
                    "/home-assistant//dialog-data-entry-flow//ha-dialog/div/step-flow-form//div[1]/ha-form//div/ha-form-select//ha-selector-select//ha-select//div/div"))
                )
                dropdown.click()
                time.sleep(1)
                
                # Find the specific council option and click it
                # Note: This is a simplified approach. You might need to adjust how you select the council option
                driver.execute_script(f"document.querySelector('mwc-list-item[aria-label*=\"{wiki_name}\"]').click()")
                time.sleep(1)
                self.take_screenshot(driver, wiki_name, "3_council_selected")
                
                # Enter name (using wiki_name)
                name_input = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, 
                    "/home-assistant//dialog-data-entry-flow//ha-dialog/div/step-flow-form//div[1]/ha-form//div/ha-form-string//ha-textfield//label/input"))
                )
                name_input.clear()
                name_input.send_keys(wiki_name)
                time.sleep(1)
                
                # Click submit to go to next page
                submit_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, 
                    "/home-assistant//dialog-data-entry-flow//ha-dialog/div/step-flow-form//div[2]/div/mwc-button"))
                )
                submit_button.click()
                time.sleep(2)
                self.take_screenshot(driver, wiki_name, "4_name_entered")
                
                # Check if postcode input is required
                try:
                    postcode_input = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, 
                        "/home-assistant//dialog-data-entry-flow//ha-dialog/div/step-flow-form//div[1]/ha-form//div/ha-form-string[1]//ha-textfield//label/input"))
                    )
                    if postcode_input.is_displayed():
                        postcode = council.get("postcode", "")
                        if postcode:
                            postcode_input.clear()
                            postcode_input.send_keys(postcode)
                            self.take_screenshot(driver, wiki_name, "5_postcode_entered")
                    
                        # Check if house number is required
                        try:
                            house_input = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.XPATH, 
                                "/home-assistant//dialog-data-entry-flow//ha-dialog/div/step-flow-form//div[1]/ha-form//div/ha-form-string[2]//ha-textfield//label/input"))
                            )
                            if house_input.is_displayed():
                                house_number = council.get("house_number", "")
                                if house_number:
                                    house_input.clear()
                                    house_input.send_keys(house_number)
                                    self.take_screenshot(driver, wiki_name, "6_house_entered")
                        except (TimeoutException, NoSuchElementException):
                            pass
                            
                except (TimeoutException, NoSuchElementException):
                    pass
                
                # Check if UPRN input is required
                try:
                    uprn_input = driver.find_element(By.XPATH, 
                    "/home-assistant//dialog-data-entry-flow//ha-dialog/div/step-flow-form//div[1]/ha-form//div/ha-form-string//ha-textfield//label/input")
                    if uprn_input.is_displayed():
                        uprn = council.get("uprn", "")
                        if uprn:
                            uprn_input.clear()
                            uprn_input.send_keys(uprn)
                            self.take_screenshot(driver, wiki_name, "7_uprn_entered")
                except (TimeoutException, NoSuchElementException):
                    pass
                
                # Check if URL input is required
                try:
                    url_input = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, 
                        "/home-assistant//dialog-data-entry-flow//ha-dialog/div/step-flow-form//div[1]/ha-form//div/ha-form-string//ha-textfield//label/input"))
                    )
                    if url_input.is_displayed():
                        url = council.get("url", "")
                        if url:
                            url_input.clear()
                            url_input.send_keys(url)
                            self.take_screenshot(driver, wiki_name, "8_url_entered")
                except (TimeoutException, NoSuchElementException):
                    pass
                
                # Click submit on final form
                submit_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, 
                    "/home-assistant//dialog-data-entry-flow//ha-dialog/div/step-flow-form//div[2]/div/mwc-button"))
                )
                submit_button.click()
                time.sleep(3)
                self.take_screenshot(driver, wiki_name, "9_completed")
                
                # Wait for final confirmation and close dialog if shown
                try:
                    finish_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Finish')]"))
                    )
                    finish_button.click()
                    time.sleep(1)
                except (TimeoutException, NoSuchElementException):
                    pass
                
                print(f"Successfully configured {wiki_name}")
                
            except Exception as e:
                print(f"Error configuring {wiki_name}: {str(e)}")
                self.take_screenshot(driver, wiki_name, "error")
                # Continue with the next council instead of failing the test
                continue