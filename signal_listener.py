import socketio
import logging
import sys
import signal
import yaml
import time
import threading
from local_systems import TradeExecutor
import jwt
import json
from datetime import datetime, timedelta
import os
import platform

# === Load Config ===
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

SERVER_URL = config.get('server_url')
ACCESS_TOKEN = config.get('access_token')
EMAIL = config.get("credentials").get("email")
PHONE_NUMBER = config.get("credentials").get("phone_number")
MAX_LOSS_COUNT = config.get("max_loss_count", 5)
MAX_PROFIT_COUNT = config.get("max_profit_count", 10)
TOTAL_TRADES = config.get("max_loss_count", 5)
INITIAL_CAPITAL = config.get('initial_capital', 1)
JWT_SECRET = "YOUR_SECRET_HERE"          

class TradeLimits:
    def __init__(self, max_loss_count, max_profit_count, total_trades):
        self.max_trades = total_trades      # Maximum allowed trades
        self.max_losses = max_loss_count          # Maximum consecutive losses
        self.max_wins = max_profit_count         # Maximum consecutive wins
        self.trade_count = 0          # Current trade count
        self.consecutive_losses = 0   # Current losing streak
        self.consecutive_wins = 0     # Current winning streak
        self.trading_enabled = True   # Master switch for trading

trade_limits = TradeLimits(MAX_LOSS_COUNT, MAX_PROFIT_COUNT, TOTAL_TRADES)

# === Logger Setup ===
logger = logging.getLogger('SignalListener')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

file_handler = logging.FileHandler('listener.log', encoding='utf-8')
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)


def wait_until(trade_time_str):
    try:
        now = datetime.now()
        
        # Parse trade_time (HH:MM) into today's datetime
        trade_time = datetime.strptime(trade_time_str, "%H:%M").time()
        target_time = datetime.combine(now.date(), trade_time)

        # 🧠 Use frozen 'now' for comparison
        if target_time <= now:
            target_time += timedelta(days=1)

        seconds_to_wait = (target_time - now).total_seconds()

        if seconds_to_wait > 1:
            print(f"⏳ Waiting for {int(seconds_to_wait)} seconds until {target_time.strftime('%H:%M:%S')}...")
            time.sleep(seconds_to_wait)

        print("✅ Reached target time!")
    except ValueError as e:
        print(f"❌ Invalid time format '{trade_time_str}'. Expected 'HH:MM'. Error: {e}")

# === Globals ===
sio = socketio.Client(
    reconnection=True,
    reconnection_attempts=9999,
    reconnection_delay=1,
    reconnection_delay_max=60,
    randomization_factor=0.5,  # Add randomness to avoid thundering herd
)


executor = TradeExecutor()
executor_lock = threading.Lock()

executor.set_initial_investment_amount(INITIAL_CAPITAL)

# === Socket Events ===
@sio.event
def connect():
    logger.info('✅ Connected to server')

@sio.event
def disconnect():
    logger.warning('⚠️ Disconnected from server')

@sio.event
def connect_error(data):
    logger.error(f"❌ Connection error: {data}")

@sio.on('broadcast')
def on_signal(data):
    try:
        if isinstance(data, str):
            data = json.loads(data)
        with executor_lock:
            logger.info(f"📩 Signal received: {data}")
            action = data.get('action').lower()

            if 'pair' in data.keys():
                pair = f"{data.get('pair')} (OTC)"
                
                if pair == 'INT/STK (OTC)':
                    pair = "Intel (OTC)"
                executor.set_investment_amount(int(INITIAL_CAPITAL))
                executor.select_asset(pair)

                trade_time = data.get('time')
                wait_until(trade_time)
                time_field = 1
            else:
                time_field = int(data.get('field1'))

                if action == 'submit':
                    # set amount & asset
                    price_field = data.get('field2')
                    instrument = data.get('dropdown')
                    executor.set_investment_amount(float(price_field), multiplier=True)
                    executor.select_asset(instrument)
                    return

            # Check limits
            if trade_limits.max_losses <= trade_limits.consecutive_losses:
                logger.warning("🚫 Max losses reached.")
                return
            if trade_limits.max_wins <= trade_limits.consecutive_wins:
                logger.warning("🚫 Max wins reached.")
                return

            if action in ['up', 'down']:
                executor.place_trade(action.upper())

                # Start non-blocking result checker
                def result_callback(is_loss):
                    if is_loss:
                        trade_limits.consecutive_losses += 1
                        trade_limits.consecutive_wins = 0
                        logger.info(f"📉 Loss recorded. Total: {trade_limits.consecutive_losses}")
                    else:
                        trade_limits.consecutive_wins += 1
                        trade_limits.consecutive_losses = 0
                        logger.info(f"📈 Win recorded. Total: {trade_limits.consecutive_wins}")

                executor.check_profit_loss(time_field, callback=result_callback)

            else:
                logger.warning(f"⚠️ Unknown action received: {action}")

    except Exception as e:
        logger.error(f"❗ Exception while handling signal: {e}")

# === Stop Signal Handling ===
def get_stop_file_path():
    """Get the path to the stop signal file"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stop_signal.flag')

def check_stop_signal():
    """Check if stop signal file exists"""
    return os.path.exists(get_stop_file_path())

def cleanup_stop_signal():
    """Clean up the stop signal file if it exists"""
    try:
        stop_file = get_stop_file_path()
        if os.path.exists(stop_file):
            os.remove(stop_file)
            logger.info("🧹 Cleaned up stop signal file")
    except Exception as e:
        logger.error(f"❌ Error cleaning up stop signal file: {e}")

def graceful_shutdown():
    """Perform graceful shutdown"""
    logger.info('🛑 Shutting down gracefully...')
    try:
        # Disconnect from socket server if connected
        if sio.connected:
            sio.disconnect()
            logger.info("📡 Disconnected from server")
    except Exception as e:
        logger.error(f"❌ Error disconnecting from server: {e}")
    
    # Close the executor
    try:
        executor.close()
        logger.info("🔒 Executor closed")
    except Exception as e:
        logger.error(f"❌ Error closing executor: {e}")
    
    # Clean up stop signal file
    cleanup_stop_signal()
    
    logger.info("👋 Shutdown complete")
    sys.exit(0)

def stop_signal_monitor():
    """Monitor for stop signals from Flask server"""
    logger.info("👀 Starting stop signal monitor")
    while True:
        try:
            if check_stop_signal():
                logger.info('🛑 Stop signal received from Flask server...')
                graceful_shutdown()
            time.sleep(1)  # Check every second
        except Exception as e:
            logger.error(f"❌ Error in stop signal monitor: {e}")
            time.sleep(5)

# === Heartbeat Monitor ===
def heartbeat_monitor():
    """Monitor connection status"""
    while True:
        try:
            if not sio.connected:
                logger.warning("🔌 Socket disconnected")
            else:
                logger.debug("❤️ Socket is alive")
            time.sleep(30)
        except Exception as e:
            logger.error(f"❌ Error in heartbeat monitor: {e}")
            time.sleep(30)

# === Signal Handler for Keyboard Interrupt ===
def keyboard_interrupt_handler(sig, frame):
    """Handle keyboard interrupts"""
    logger.info('🛑 Keyboard interrupt received, shutting down...')
    graceful_shutdown()

# Setup signal handlers for keyboard interrupts
signal.signal(signal.SIGINT, keyboard_interrupt_handler)
signal.signal(signal.SIGTERM, keyboard_interrupt_handler)

def generate_token(email, phone, access_token, secret):
    """Generate JWT token for authentication"""
    payload = {
        "email": email,
        "phone": phone,
        "access_token": access_token,
    }
    return jwt.encode(payload, secret, algorithm="HS256")

def stop():
    """Public stop method that can be called externally"""
    logger.info("⏹️ Stop method called")
    graceful_shutdown()

# === Reconnect Loop ===
def connect_to_server():
    """Connect to the trading server"""
    token = generate_token(EMAIL, PHONE_NUMBER, ACCESS_TOKEN, JWT_SECRET)
    
    while True:
        try:
            logger.info(f"🔌 Attempting connection to {SERVER_URL}...")
            sio.connect(SERVER_URL, transports=["websocket"])  
            sio.emit("auth", {"token": token})
            logger.info("✅ Connected and authenticated successfully")
            sio.wait()  # This will block until disconnected
        except Exception as e:
            logger.error(f"❗ Connection failed: {e}")
            logger.info("🔄 Reconnecting in 10 seconds...")
            time.sleep(10)
        
        # Check if we should stop during reconnection attempts
        if check_stop_signal():
            graceful_shutdown()

# === Main Entrypoint ===
def main():
    """Main function to start the trading system"""
    logger.info('🚀 Starting Trade Executor and Signal Listener...')
    logger.info(f'📊 Platform: {platform.system()} {platform.release()}')
    
    # Clean up any existing stop signal file on startup
    cleanup_stop_signal()
    
    # Start monitoring threads
    threading.Thread(target=heartbeat_monitor, daemon=True).start()
    threading.Thread(target=stop_signal_monitor, daemon=True).start()
    
    logger.info("✅ All monitors started")
    
    # Start the main connection loop
    connect_to_server()

if __name__ == '__main__':
    main()