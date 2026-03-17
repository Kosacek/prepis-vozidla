"""
Launcher for Přepis Vozidla app.
Starts Flask in a background thread, then opens the browser.
"""
import sys
import os
import threading
import webbrowser
import time

# When running as a PyInstaller bundle, data files are in sys._MEIPASS
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Make sure app.py can find its data files
os.chdir(BASE_DIR)

from app import app

PORT = 5050

def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{PORT}")

threading.Thread(target=open_browser, daemon=True).start()

# Start auto-update check in background (only when packaged)
if getattr(sys, 'frozen', False):
    try:
        import updater
        threading.Thread(target=updater.background_check, daemon=True).start()
    except Exception:
        pass

app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)
