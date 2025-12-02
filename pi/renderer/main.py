#!/usr/bin/env python3
import json
import time
from pathlib import Path

import requests
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

# Paths
BASE_DIR = Path(__file__).parent
SETTINGS_FILE = BASE_DIR / "settings.json"


# ---------------------------------------------------------------------------
# Settings + Matrix setup
# ---------------------------------------------------------------------------

def load_settings():
    """
    Load renderer settings from settings.json.
    """
    with open(SETTINGS_FILE, "r") as f:
        data = json.load(f)

    # Basic defaults / safety
    data.setdefault("api_base_url", "")
    data.setdefault("live_messages_path", "/messages/live")
    data.setdefault("poll_interval_sec", 5)
    data.setdefault("scroll_delay_sec", 0.03)
    data.setdefault("panel_rows", 32)
    data.setdefault("panel_cols", 64)
    data.setdefault("chain_length", 1)
    data.setdefault("parallel", 1)
    data.setdefault("hardware_mapping", "adafruit-hat")
    data.setdefault("brightness", 70)
    data.setdefault("font_path", "/home/pi/rpi-rgb-led-matrix/fonts/7x13.bdf")
    data.setdefault("fallback_message", "TXT 647-930-4995")
    data.setdefault("fallback_idle_seconds", 5)

    return data


def create_matrix(settings):
    """
    Create and configure the RGBMatrix from settings.
    """
    options = RGBMatrixOptions()
    options.rows = settings["panel_rows"]
    options.cols = settings["panel_cols"]
    options.chain_length = settings["chain_length"]
    options.parallel = settings["parallel"]
    options.hardware_mapping = settings["hardware_mapping"]
    options.brightness = settings["brightness"]
    options.drop_privileges = False

    matrix = RGBMatrix(options=options)
    return matrix


def build_live_messages_url(settings):
    """
    Construct the full /messages/live URL from base + path.
    """
    base = (settings.get("api_base_url") or "").rstrip("/")
    path = settings.get("live_messages_path", "/messages/live")
    if not path.startswith("/"):
        path = "/" + path
    url = base + path
    return url


# ---------------------------------------------------------------------------
# Backend polling
# ---------------------------------------------------------------------------

def fetch_live_messages(settings, url):
    """
    Call the moderation API /messages/live endpoint and return a list of messages.

    Expects response shape:
        { "messages": [ { "body": "text", ... }, ... ] }
    """
    try:
        print(f"[Pi] Fetching live messages from: {url}")
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        data = resp.json()

        messages = data.get("messages") or data.get("items") or []
        print(f"[Pi] Fetched {len(messages)} live message(s)")
        return messages

    except Exception as e:
        print(f"[Pi] Error fetching live messages: {e}")
        return []


# ---------------------------------------------------------------------------
# Rendering / scrolling
# ---------------------------------------------------------------------------

def scroll_text(matrix, text, settings):
    """
    Scroll a single line of text from right to left on the matrix.
    """
    if not text:
        return

    scroll_delay = settings.get("scroll_delay_sec", 0.03)
    font_path = settings.get("font_path", "/home/pi/rpi-rgb-led-matrix/fonts/7x13.bdf")

    font = graphics.Font()
    font.LoadFont(font_path)

    # Yellow text
    color = graphics.Color(255, 255, 0)

    offscreen_canvas = matrix.CreateFrameCanvas()
    width = offscreen_canvas.width
    height = offscreen_canvas.height

    # Baseline for text (roughly vertically centered)
    text_y = height // 2 + 4

    # Measure text width
    text_width = graphics.DrawText(offscreen_canvas, font, 0, text_y, color, text)

    # Start from the right edge
    pos_x = width

    print(f"[Pi] Scrolling text: '{text}'")

    while pos_x + text_width > 0:
        offscreen_canvas.Clear()
        graphics.DrawText(offscreen_canvas, font, pos_x, text_y, color, text)
        pos_x -= 1
        time.sleep(scroll_delay)
        offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run():
    settings = load_settings()
    matrix = create_matrix(settings)

    poll_interval = settings.get("poll_interval_sec", 5)
    fallback_message = settings.get("fallback_message", "TXT 647-930-4995")
    fallback_idle = settings.get("fallback_idle_seconds", 5)

    live_url = build_live_messages_url(settings)
    print("[Pi] Loaded settings from:", SETTINGS_FILE)
    print("[Pi] Using live messages URL:", live_url)
    print("[Pi] Poll interval (sec):", poll_interval)

    last_fetch_ts = 0
    cached_messages = []

    while True:
        now = time.time()

        # Refresh messages from backend based on poll interval
        if now - last_fetch_ts >= poll_interval:
            cached_messages = fetch_live_messages(settings, live_url)
            last_fetch_ts = now

        if cached_messages:
            # Scroll each approved message body in order
            for msg in list(cached_messages):
                body = str(msg.get("body", "")).strip()
                if body:
                    scroll_text(matrix, body, settings)
        else:
            # No live messages -> show fallback prompt once, then idle briefly
            scroll_text(matrix, fallback_message, settings)
            time.sleep(fallback_idle)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[Pi] Exiting on Ctrl+C")
