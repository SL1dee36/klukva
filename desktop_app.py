"""
Klukva Desktop Application
Standalone local desktop app running the Klukva task tracker with embedded WebView2
and automatic repository update integration.
"""

import os
import sys
import time
import socket
import threading
import webbrowser
import uvicorn
import webview

def find_open_port(preferred_port: int = 3002) -> int:
    for port in [preferred_port, 3003, 3004, 3005, 3006, 8088]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return preferred_port


def run_server(port: int):
    # Set sys.path so backend imports work properly in all environments
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        parent = os.path.dirname(exe_dir)
        sys.path.insert(0, getattr(sys, "_MEIPASS", exe_dir))
        sys.path.insert(0, parent)
        sys.path.insert(0, exe_dir)
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from main import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


def wait_for_server(port: int, max_retries: int = 50) -> bool:
    for _ in range(max_retries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def main():
    port = find_open_port(3002)
    os.environ["KLUKVA_PORT"] = str(port)

    # Start FastAPI server in a background daemon thread
    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()

    # Wait until FastAPI starts accepting connections
    server_ready = wait_for_server(port)
    url = f"http://127.0.0.1:{port}/"

    try:
        # Create native Edge Chromium WebView2 window
        window = webview.create_window(
            title="Klukva — Трекер задач",
            url=url,
            width=1320,
            height=860,
            min_size=(800, 600),
            text_select=True,
            confirm_close=False
        )
        webview.start(debug=False)
    except Exception as e:
        print(f"WebView2 initialization fallback: {e}")
        webbrowser.open(url)
        # Keep process alive while server is running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
