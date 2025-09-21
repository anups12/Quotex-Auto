from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import subprocess
import yaml
import threading
import logging
from datetime import datetime
import os
import sys
import signal
import time

app = Flask(__name__)
CORS(app)

# Global variables to manage the trading process
trading_process = None
trading_status = "stopped"
trading_logs = []

# Fixed server URL (not exposed in frontend)
FIXED_SERVER_URL = "http://13.60.98.167:60020/"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('TradingSystemServer')

# Get the directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Create templates directory if it doesn't exist
os.makedirs(TEMPLATES_DIR, exist_ok=True)

@app.route('/')
def serve_ui():
    # Try to serve index.html from the templates directory
    try:
        return send_from_directory(TEMPLATES_DIR, 'index.html')
    except:
        # If index.html doesn't exist, create a simple default page
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Trading System</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body>
            <div class="container mt-5">
                <h1>Trading System Control Panel</h1>
                <p>Index.html file not found. Please make sure it exists in the templates directory.</p>
                <p>Current directory: {}</p>
                <p>Templates directory: {}</p>
            </div>
        </body>
        </html>
        """.format(BASE_DIR, TEMPLATES_DIR)

@app.route('/<path:path>')
def serve_static(path):
    # Security check: prevent directory traversal
    if '..' in path or path.startswith('/'):
        return "Invalid path", 403
    
    # Only serve specific file types
    allowed_extensions = ['.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg']
    if not any(path.endswith(ext) for ext in allowed_extensions):
        return "File type not allowed", 403
    
    try:
        return send_from_directory(TEMPLATES_DIR, path)
    except FileNotFoundError:
        return "File not found", 404

@app.route('/api/start', methods=['POST'])
def start_trading():
    global trading_process, trading_status, trading_logs
    
    if trading_status == "running":
        return jsonify({"status": "error", "message": "Trading system is already running"})
    
    try:
        config_data = request.json
        
        # Validate required fields
        required_fields = ['access_token', 'email', 'password', 'phone_number']
        for field in required_fields:
            if not config_data.get(field):
                return jsonify({"status": "error", "message": f"Missing required field: {field}"})
        
        # Save configuration to config.yaml with the fixed server URL
        config_to_save = {
            'server_url': FIXED_SERVER_URL,
            'access_token': config_data.get('access_token'),
            'credentials': {
                'email': config_data.get('email'),
                'password': config_data.get('password'),
                'phone_number': config_data.get('phone_number'),
                'asset': config_data.get('asset', 'USD/GBP (OTC)'),  # Added asset field
                'demo': True if config_data.get('demo', True) == "on" else False
            },
            'max_loss_count': config_data.get('max_loss_count', 5),
            'max_profit_count': config_data.get('max_profit_count', 5),
            'max_total_trades': config_data.get('max_total_trades', 10),
            'initial_capital': config_data.get('initial_capital', 1000)
        }
        
        with open('config.yaml', 'w') as f:
            yaml.dump(config_to_save, f)
        
        # Start the trading system as a subprocess
        trading_process = subprocess.Popen(
            [sys.executable, 'signal_listener.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        trading_status = "running"
        trading_logs = []
        
        # Start a thread to capture output
        def capture_output():
            while trading_process and trading_process.poll() is None:
                try:
                    output = trading_process.stdout.readline()
                    if output:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        log_entry = f"[{timestamp}] {output.strip()}"
                        trading_logs.append(log_entry)
                        logger.info(log_entry)
                except Exception as e:
                    logger.error(f"Error reading process output: {e}")
                    break
        
        output_thread = threading.Thread(target=capture_output)
        output_thread.daemon = True
        output_thread.start()
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        trading_logs.append(f"[{timestamp}] Trading system started successfully")
        
        return jsonify({"status": "success", "message": "Trading system started"})
    
    except Exception as e:
        logger.error(f"Error starting trading: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/stop', methods=['POST'])
def stop_trading():
    global trading_process, trading_status, trading_logs
    
    if trading_status != "running":
        return jsonify({"status": "error", "message": "Trading system is not running"})
    
    try:
        # Create a stop control file - platform independent approach
        stop_file_path = os.path.join(BASE_DIR, 'stop_signal.flag')
        with open(stop_file_path, 'w') as f:
            f.write(str(datetime.now().timestamp()))
        
        # Wait for process to end gracefully
        try:
            trading_process.wait(timeout=15)  # Give more time for graceful shutdown
        except subprocess.TimeoutExpired:
            # If process doesn't terminate gracefully, force kill it
            trading_process.kill()
            trading_process.wait()
            logger.warning("Process was forcefully terminated")
        
        trading_status = "stopped"
        trading_process = None
        
        # Clean up stop file if it still exists
        if os.path.exists(stop_file_path):
            os.remove(stop_file_path)
        
        # Add a final log entry
        timestamp = datetime.now().strftime("%H:%M:%S")
        trading_logs.append(f"[{timestamp}] Trading system stopped")
        
        return jsonify({"status": "success", "message": "Trading system stopped"})
    
    except Exception as e:
        logger.error(f"Error stopping trading: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/status', methods=['GET'])
def get_status():
    global trading_status, trading_logs, trading_process
    
    # Check if process is still alive - use safe checking
    try:
        if trading_status == "running" and trading_process is not None:
            # Check if process is still running
            poll_result = trading_process.poll()
            if poll_result is not None:
                # Process has terminated
                trading_status = "stopped"
                timestamp = datetime.now().strftime("%H:%M:%S")
                trading_logs.append(f"[{timestamp}] Trading process terminated unexpectedly with exit code: {poll_result}")
                trading_process = None
    except Exception as e:
        logger.error(f"Error checking process status: {e}")
        trading_status = "stopped"
        trading_process = None
    
    return jsonify({
        "status": trading_status,
        "logs": trading_logs[-20:]  # Return last 20 log entries
    })

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)