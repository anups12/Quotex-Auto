import time
import yaml
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
import os
import threading
import certifi
import ssl

ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())


class TradeExecutor:
    def __init__(self):
        with open("config.yaml", "r") as file:
            config = yaml.safe_load(file)
        self.username = config["credentials"]["email"]
        self.password = config["credentials"]["password"]
        self.use_demo = config["credentials"]["demo"]
        self.headless_mode = False  # Start in non-headless mode
        
        # Initialize driver in non-headless mode first
        options = uc.ChromeOptions()
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        # Don't add headless argument yet
        self.driver = uc.Chrome(options=options)
        self.driver.implicitly_wait(10)
        self.lock = threading.Lock()
        
        # Login first in visible mode
        self.login_to_quotex()
        
        # After successful login, switch to headless mode
        self.switch_to_headless_mode()
        
        # Start browser monitor
        threading.Thread(target=self._monitor_browser, daemon=True).start()

    def login_to_quotex(self):
        print("🚀 Starting login process in VISIBLE mode...")
        self.driver.get("https://qxbroker.com/en/sign-in/modal/")
        time.sleep(2)
        self.driver.find_element(By.NAME, "email").send_keys(self.username)
        self.driver.find_element(By.NAME, "password").send_keys(self.password)
        self.driver.find_element(By.CSS_SELECTOR, "button.button--primary[type='submit']").click()

        WebDriverWait(self.driver, 120).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "button.asset-select__button"))
        )
        print("[INFO] Logged in successfully")

        if self.use_demo:
            self._switch_to_demo()
        
        print("✅ Login completed successfully in visible mode")

    def switch_to_headless_mode(self):
        """Switch to headless mode after successful login"""
        print("🔄 Switching to headless mode...")
        
        # Save current URL and cookies for session restoration
        current_url = self.driver.current_url
        cookies = self.driver.get_cookies()
        
        # Close the current visible browser
        self.driver.quit()
        
        # Create new options for headless mode
        options = uc.ChromeOptions()

        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        options.add_argument("--start-maximized")   # start maximized
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-software-rasterizer")
        
        # Initialize new driver in headless mode
        self.driver = uc.Chrome(options=options)
        self.driver.implicitly_wait(10)
        self.headless_mode = True
        
        # Restore session
        try:
            # Navigate to the same URL
            self.driver.get(current_url)
            
            # Restore cookies
            for cookie in cookies:
                # Remove unwanted cookie properties that might cause issues
                cookie_copy = cookie.copy()
                if 'sameSite' in cookie_copy and cookie_copy['sameSite'] not in ['Strict', 'Lax', 'None']:
                    cookie_copy['sameSite'] = 'Lax'
                self.driver.add_cookie(cookie_copy)
            
            # Refresh to apply cookies
            self.driver.refresh()
            
            # Wait for the page to load completely
            WebDriverWait(self.driver, 30).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "button.asset-select__button"))
            )
            
            print("✅ Successfully switched to headless mode with session restored")
            
        except Exception as e:
            print(f"❌ Error during headless switch: {e}")
            print("⚠️ Attempting to re-login in headless mode...")
            self._relogin_in_headless_mode()

    def _relogin_in_headless_mode(self):
        """Re-login if session restoration fails"""
        try:
            self.driver.get("https://qxbroker.com/en/sign-in/modal/")
            time.sleep(2)
            
            # Find and fill login form
            email_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "email"))
            )
            password_field = self.driver.find_element(By.NAME, "password")
            
            email_field.send_keys(self.username)
            password_field.send_keys(self.password)
            
            # Click login button
            login_button = self.driver.find_element(By.CSS_SELECTOR, "button.button--primary[type='submit']")
            login_button.click()
            
            # Wait for login to complete
            WebDriverWait(self.driver, 120).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "button.asset-select__button"))
            )
            
            if self.use_demo:
                self._switch_to_demo()
                
            print("✅ Successfully re-logged in headless mode")
            
        except Exception as e:
            print(f"❌ Failed to re-login in headless mode: {e}")
            raise Exception("Failed to switch to headless mode")

    def _switch_to_demo(self):
        try:
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'infoWrapper')]"))
            ).click()

            time.sleep(1)
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Demo Account')]"))
            ).click()
            time.sleep(2)
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.modal-account-type-changed__body-button"))
            ).click()
            print("✅ Switched to demo account")
        except Exception as e:
            print(f"⚠️ Failed to switch to demo account: {e}")

    def get_all_assets(self):
        all_assets = set()

        # Open asset selection popup
        self.driver.find_element(By.CSS_SELECTOR, "button.asset-select__button").click()

        # Handle first tab that's already open by default
        try:
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".assets-table__name span"))
            )
            asset_elements = self.driver.find_elements(By.CSS_SELECTOR, ".assets-table__name span")
            for asset in asset_elements:
                all_assets.add(asset.text.strip())
            print(f"✅ Found {len(asset_elements)} assets in default (first) category")
        except TimeoutException:
            print("⚠️ No assets found in default category")

        # Continue with the rest of the categories
        visited_categories = set()

        filter_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".asset-select__search-filter")

        for i in range(len(filter_buttons)):
            filter_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".asset-select__search-filter")
            button = filter_buttons[i]
            category_name = button.text.strip()

            # Skip if it's already visited (including the default one)
            if category_name in visited_categories:
                continue
            visited_categories.add(category_name)

            button.click()

            try:
                WebDriverWait(self.driver, 3).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".assets-table__name span"))
                )
                asset_elements = self.driver.find_elements(By.CSS_SELECTOR, ".assets-table__name span")
                for asset in asset_elements:
                    all_assets.add(asset.text.strip())
                print(f"✅ Found {len(asset_elements)} assets in category '{category_name}'")
            except TimeoutException:
                print(f"⚠️ No assets found in category '{category_name}'")
                continue

        print(f"\n✅ Total unique assets found: {len(all_assets)}")
        return list(all_assets)

    
    def select_asset(self, asset_text):
        # Open asset selection popup
        try:
            self.driver.find_element(By.CSS_SELECTOR, "button.asset-select__button").click()
        except Exception:
            raise Exception("❌ Unable to click asset selection button.")

        time.sleep(0.5)  # Let the popup animate open

        # Get all category filter buttons
        filter_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".asset-select__search-filter")

        for button in filter_buttons:
            try:
                button.click()
                time.sleep(2)  # Give it time to load category assets

                # XPath to find asset text (case-sensitive, adjust if needed)
                asset_xpath = f"//span[contains(text(), \"{asset_text}\")]"

                # Wait for the element to be present in DOM
                asset_element = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, asset_xpath))
                )

                # Scroll asset into view (this is crucial)
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", asset_element)

                # Wait until it's clickable
                WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, asset_xpath))
                )

                asset_element.click()
                print(f"✅ Asset '{asset_text}' selected.")
                return

            except TimeoutException:
                print(f"⚠️ Asset '{asset_text}' not found or not clickable in category '{button.text.strip()}'. Trying next...")
                continue
            except Exception as e:
                print(f"⚠️ Unexpected error: {e}")
                continue

        raise Exception(f"❗ Asset '{asset_text}' not found in any category.")

    def set_initial_investment_amount(self, target_amount):
        invest_container = self.driver.find_element(
            By.CSS_SELECTOR, "div.input-control.input-control--number"
        )

        def get_amount():
            val = invest_container.find_element(By.CSS_SELECTOR, "input.input-control__input").get_attribute("value")
            return int(val.replace("$", "").replace(",", "").replace("₹", "").strip())
        
        previous_amount = get_amount()
        input_field = invest_container.find_element(By.CSS_SELECTOR, "input.input-control__input")
        input_field.send_keys(Keys.CONTROL + "a")  # Select all
        input_field.send_keys(int(target_amount))  # Type new value


    def set_investment_amount(self, target_amount, multiplier=False):
        invest_container = self.driver.find_element(
            By.CSS_SELECTOR, "div.input-control.input-control--number"
        )

        def get_amount():
            val = invest_container.find_element(By.CSS_SELECTOR, "input.input-control__input").get_attribute("value")
            return int(val.replace("$", "").replace(",", "").replace("₹", "").strip())
        
        previous_amount = get_amount()
        input_field = invest_container.find_element(By.CSS_SELECTOR, "input.input-control__input")
        input_field.send_keys(Keys.CONTROL + "a")  # Select all

        if multiplier:
            print("Delete me values ", int(round(target_amount * previous_amount)))
            input_field.send_keys(int(round(target_amount * previous_amount)))  # Type new value
        else:
            input_field.send_keys(target_amount)


    def place_trade(self, direction):
        with self.lock:
            if direction.upper() == "UP":
                self.driver.find_element(By.CSS_SELECTOR, "button.call-btn").click()
            else:
                self.driver.find_element(By.CSS_SELECTOR, "button.put-btn").click()
            print(f"[ACTION] Placed trade: {direction}")
            time.sleep(1)

    def close(self):
        self.driver.quit()

    def _monitor_browser(self):
        while True:
            try:
                # This throws an exception if the browser is closed
                _ = self.driver.title
            except Exception:
                print("🧹 Browser closed. Shutting down entire program.")
                os._exit(0)  # Forcefully exits the whole program
            time.sleep(2)

    def check_profit_loss(self, time_field, callback=None):
        def _check():
            time.sleep(time_field * 60)  # wait for trade to settle
            try:
                value_element = self.driver.find_element(By.CLASS_NAME, "trades-list-item__delta-right")
                value = value_element.text.strip()
                actual_value = float(value.split(' ')[0])
                is_loss = actual_value <= 0
                print(f"[RESULT] Trade result: {'LOSS' if is_loss else 'WIN'} ({actual_value})")
                if callback:
                    callback(is_loss)
            except Exception as e:
                print(f"[ERROR] Unable to check profit/loss: {e}")
                if callback:
                    callback(True)  # assume loss if unknown

        threading.Thread(target=_check, daemon=True).start()