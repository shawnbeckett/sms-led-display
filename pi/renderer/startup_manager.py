#!/usr/bin/env python3
"""
SMS-LED startup manager.

Runs on boot (via systemd) and decides:

1. If the Pi has working Wi-Fi + internet:
   - Log the SSID + status.
   - Show "WiFi OK: <SSID>" briefly on the LED panel.
   - Start the main renderer (pi/renderer/main.py).
   - Then sleep forever so systemd keeps the process around.

2. If the Pi does NOT have working Wi-Fi after a grace period:
   - Start the SMS-LED access point using wifi/ap_control.sh.
   - Show a persistent instruction on the LED panel:
       "No WiFi. Connect to SMS-LED and go to http://192.168.4.1"
   - Sleep forever. The Wi-Fi config UI will write wpa_supplicant.conf and reboot.
"""

import os
import socket
import subprocess
import time
from typing import Optional, Tuple

from status_display import show_wifi_ok, show_wifi_setup_instructions

# Paths on the Pi
REPO_ROOT = "/home/pi/sms-led-display"
RENDERER_DIR = os.path.join(REPO_ROOT, "pi", "renderer")
RENDERER_MAIN = os.path.join(RENDERER_DIR, "main.py")
AP_CONTROL = os.path.join(RENDERER_DIR, "wifi", "ap_control.sh")

# Python in the LED matrix virtualenv on the Pi
VENV_PYTHON = "/home/pi/virtualenvs/led-matrix-env/bin/python3"

# Connectivity check settings
CONNECTIVITY_HOST = "1.1.1.1"   # Cloudflare; any stable IP is fine
CONNECTIVITY_PORT = 443
CONNECTIVITY_TIMEOUT_SEC = 2.0

MAX_WAIT_FOR_WIFI_SEC = 35       # Total time to give Wi-Fi to come up
WIFI_POLL_INTERVAL_SEC = 5       # Time between checks


def log(msg: str) -> None:
    """Lightweight logger to stdout (visible in journalctl)."""
    print(f"[SMS-LED startup] {msg}", flush=True)


def get_current_ssid() -> Optional[str]:
    """
    Return the SSID of the current Wi-Fi network, or None if not associated.
    Uses `iwgetid -r`.
    """
    try:
        out = subprocess.check_output(
            ["iwgetid", "-r"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            return out
        return None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def has_internet_connectivity() -> bool:
    """
    Attempt a simple TCP connection to a well-known IP to verify internet.
    We don't need HTTP/TLS, just that routing + IP are working.
    """
    try:
        with socket.create_connection(
            (CONNECTIVITY_HOST, CONNECTIVITY_PORT),
            timeout=CONNECTIVITY_TIMEOUT_SEC,
        ):
            return True
    except OSError:
        return False


def wait_for_wifi_and_internet() -> Tuple[bool, Optional[str]]:
    """
    Wait up to MAX_WAIT_FOR_WIFI_SEC for Wi-Fi + internet connectivity.

    Returns:
        (True, ssid)  if we detect internet connectivity (SSID may be None).
        (False, ssid) if we time out without confirming internet.
    """
    deadline = time.time() + MAX_WAIT_FOR_WIFI_SEC
    last_ssid: Optional[str] = None

    log("Waiting for Wi-Fi and internet connectivity...")

    while time.time() < deadline:
        ssid = get_current_ssid()
        if ssid is not None:
            last_ssid = ssid
            log(f"Detected Wi-Fi SSID: {ssid}")

        if has_internet_connectivity():
            log("Internet connectivity detected.")
            return True, ssid or last_ssid

        log("No internet yet; will retry...")
        time.sleep(WIFI_POLL_INTERVAL_SEC)

    log("Timed out waiting for Wi-Fi/internet.")
    return False, last_ssid


def start_renderer() -> None:
    """
    Start the main renderer (main.py) using the LED-matrix virtualenv python.
    """
    if not os.path.exists(RENDERER_MAIN):
        log(f"Renderer script not found at {RENDERER_MAIN}")
        return

    log(f"Starting renderer: {RENDERER_MAIN}")
    subprocess.Popen(
        [VENV_PYTHON, RENDERER_MAIN],
        cwd=RENDERER_DIR,
    )


def start_access_point() -> None:
    """
    Start the SMS-LED access point using ap_control.sh start.
    This will:
      - Stop the client Wi-Fi stack
      - Configure wlan0 as 192.168.4.1
      - Start dnsmasq + hostapd (SSID: SMS-LED)
    """
    if not os.path.exists(AP_CONTROL):
        log(f"AP control script not found at {AP_CONTROL}")
        return

    log("Starting SMS-LED access point (AP mode).")
    try:
        subprocess.check_call(
            [AP_CONTROL, "start"],
            cwd=os.path.dirname(AP_CONTROL),
        )
        log("AP mode started successfully.")
    except subprocess.CalledProcessError as e:
        log(f"Failed to start AP mode: {e}")


def main() -> None:
    # On boot, give the system a brief moment before we start checking.
    time.sleep(5)

    ok, ssid = wait_for_wifi_and_internet()

    if ok:
        if ssid:
            log(f"Wi-Fi OK. Connected to SSID: {ssid}")
        else:
            log("Wi-Fi OK. SSID unknown but internet is reachable.")

        # Show Wi-Fi status briefly on the LED panel.
        try:
            show_wifi_ok(ssid)
        except Exception as e:
            log(f"Error in show_wifi_ok: {e}")

        # Then launch the main renderer, which will take over the panel.
        start_renderer()
    else:
        log("No working internet detected; enabling SMS-LED hotspot.")

        # Start AP mode first so the network is ready before we tell user.
        start_access_point()

        # Show persistent setup instructions on the panel.
        try:
            show_wifi_setup_instructions()
        except Exception as e:
            log(f"Error in show_wifi_setup_instructions: {e}")

    # Keep this process alive so systemd treats the service as active.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
