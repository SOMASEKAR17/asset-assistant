from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "engine"))

import uvicorn
import webview

from caa.api import create_app
from caa.config import load_settings
from caa.services import Services


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free port")


class Bridge:
    def __init__(self):
        self.window = None

    def pick_folder(self):
        dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        result = self.window.create_file_dialog(dialog)
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result


def main() -> None:
    settings = load_settings()
    services = Services(settings)
    port = free_port(settings.port)
    server = uvicorn.Server(uvicorn.Config(create_app(services), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    bridge = Bridge()
    window = webview.create_window("Creator Asset Assistant", f"http://127.0.0.1:{port}/", width=1440, height=900,
                                   min_size=(1024, 680), background_color="#222326", js_api=bridge)
    bridge.window = window
    try:
        webview.start()
    finally:
        server.should_exit = True
        services.close()


if __name__ == "__main__":
    main()
