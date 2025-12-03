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
    data.setdefault("ticker_text", data.get("fallback_message", "TXT 647-930-4995"))
    data.setdefault("ticker_font_path", "/home/pi/rpi-rgb-led-matrix/fonts/tom-thumb.bdf")
    data.setdefault("ticker_scroll_delay_sec", 0.07)
    data.setdefault("ticker_gap_px", 10)

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

def draw_and_step_ticker(canvas, settings, ticker_state, ticker_font, ticker_color):
    """
    Draw the small ticker text at the bottom of the display and advance it
    at a slower rate than the main message scroll.
    """
    ticker_text = ticker_state.get("text", "")
    if not ticker_text:
        return

    ticker_delay = settings.get("ticker_scroll_delay_sec", 0.07)
    now = time.time()
    if now - ticker_state.get("last_step", 0) >= ticker_delay:
        ticker_state["pos_x"] = ticker_state.get("pos_x", canvas.width) - 1
        ticker_state["last_step"] = now

    width = ticker_state.get("width", 0)
    if width <= 0:
        width = graphics.DrawText(canvas, ticker_font, 0, 0, ticker_color, ticker_text) or 0
        ticker_state["width"] = width

    gap = settings.get("ticker_gap_px", 10)

    # Wrap when the first instance is fully off screen
    if ticker_state["pos_x"] + width < 0:
        ticker_state["pos_x"] += width + gap

    text_y = canvas.height - 1  # bottom row baseline for the tiny font
    x1 = ticker_state["pos_x"]
    x2 = x1 + width + gap

    graphics.DrawText(canvas, ticker_font, x1, text_y, ticker_color, ticker_text)
    graphics.DrawText(canvas, ticker_font, x2, text_y, ticker_color, ticker_text)


def scroll_text(matrix, text, settings, fonts, ticker_state):
    """
    Scroll a single line of text from right to left on the matrix while
    keeping a tiny ticker moving along the bottom.
    """
    if not text:
        return

    scroll_delay = settings.get("scroll_delay_sec", 0.03)
    font = fonts["main_font"]
    color = fonts["main_color"]

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
        draw_and_step_ticker(
            offscreen_canvas,
            settings,
            ticker_state,
            fonts["ticker_font"],
            fonts["ticker_color"],
        )
        pos_x -= 1
        time.sleep(scroll_delay)
        offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run():
    settings = load_settings()
    matrix = create_matrix(settings)

    # Load fonts once
    main_font = graphics.Font()
    main_font.LoadFont(settings.get("font_path", "/home/pi/rpi-rgb-led-matrix/fonts/7x13.bdf"))
    ticker_font = graphics.Font()
    ticker_font.LoadFont(settings.get("ticker_font_path", "/home/pi/rpi-rgb-led-matrix/fonts/tom-thumb.bdf"))

    fonts = {
        "main_font": main_font,
        "main_color": graphics.Color(255, 255, 0),  # yellow
        "ticker_font": ticker_font,
        "ticker_color": graphics.Color(200, 200, 200),
    }

    poll_interval = settings.get("poll_interval_sec", 5)
    fallback_message = settings.get("fallback_message", "TXT 647-930-4995")
    fallback_idle = settings.get("fallback_idle_seconds", 5)
    ticker_text = settings.get("ticker_text", fallback_message)

    live_url = build_live_messages_url(settings)
    print("[Pi] Loaded settings from:", SETTINGS_FILE)
    print("[Pi] Using live messages URL:", live_url)
    print("[Pi] Poll interval (sec):", poll_interval)

    # Ticker state: start from the right edge
    temp_canvas = matrix.CreateFrameCanvas()
    ticker_width = graphics.DrawText(
        temp_canvas,
        fonts["ticker_font"],
        0,
        temp_canvas.height - 1,
        fonts["ticker_color"],
        ticker_text,
    ) or 0
    temp_canvas.Clear()

    ticker_state = {
        "text": ticker_text,
        "pos_x": temp_canvas.width,
        "width": ticker_width,
        "last_step": 0.0,
    }

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
                    scroll_text(matrix, body, settings, fonts, ticker_state)
        else:
            # No live messages -> only show the small bottom ticker (no full-screen scroll)
            end_idle = time.time() + fallback_idle if fallback_idle > 0 else now
            while time.time() < end_idle:
                canvas = matrix.CreateFrameCanvas()
                canvas.Clear()
                draw_and_step_ticker(
                    canvas,
                    settings,
                    ticker_state,
                    fonts["ticker_font"],
                    fonts["ticker_color"],
                )
                canvas = matrix.SwapOnVSync(canvas)
                time.sleep(settings.get("scroll_delay_sec", 0.03))


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[Pi] Exiting on Ctrl+C")
