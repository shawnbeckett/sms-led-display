#!/usr/bin/env python3
import json
import time
import threading
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
    data.setdefault("fallback_message", "^^TXT: 647-930-4995^^")
    data.setdefault("fallback_idle_seconds", 5)
    data.setdefault("ticker_text", data.get("fallback_message", "^^TXT: 647-930-4995^^"))
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


def get_message_id(msg):
    """
    Derive a stable ID for a message.

    Prefer backend IDs, fall back to body text if needed.
    """
    body = str(msg.get("body", "")).strip()
    return msg.get("pk") or msg.get("message_id") or body


# ---------------------------------------------------------------------------
# Backend polling (HTTP helpers)
# ---------------------------------------------------------------------------

def fetch_live_messages(settings, url):
    """
    Call the moderation API /messages/live endpoint and return a list of messages.

    Expects response shape:
        { "messages": [ { "body": "text", ... }, ... ], "screen_muted": bool }
    """
    try:
        print(f"[Pi] Fetching live messages from: {url}")
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        data = resp.json()

        messages = data.get("messages") or data.get("items") or []
        screen_muted = bool(data.get("screen_muted", False))
        print(
            f"[Pi] Fetched {len(messages)} live message(s); mute is "
            f"{'ON' if screen_muted else 'OFF'}"
        )
        return {
            "messages": messages,
            "screen_muted": screen_muted,
        }

    except Exception as e:
        print(f"[Pi] Error fetching live messages: {e}")
        return {"messages": [], "screen_muted": False}


def mark_message_played(settings, message_id):
    """
    Notify the backend that a message has been played so UI can start countdowns.

    This implementation is fully async: it spawns a background thread
    so the render loop is never blocked by HTTP.
    """
    if not message_id:
        return

    def worker():
        try:
            base = (settings.get("api_base_url") or "").rstrip("/")
            played_url = base + "/messages/played"
            resp = requests.post(
                played_url,
                json={"message_id": message_id},
                timeout=1,  # keep this short; it's fire-and-forget
            )
            if resp.status_code != 200:
                print(f"[Pi] mark_played failed {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[Pi] Error marking played for {message_id}: {e}")

    t = threading.Thread(target=worker, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Background polling thread
# ---------------------------------------------------------------------------

def start_live_polling_thread(settings, live_url, poll_interval, shared_state):
    """
    Start a background thread which periodically polls /messages/live and
    updates shared_state with the latest messages + screen_muted status.

    shared_state is a dict with keys:
      - "messages": latest raw list from the backend
      - "screen_muted": bool
      - "last_update": monotonic timestamp of last successful poll
    """

    def poller():
        while True:
            data = fetch_live_messages(settings, live_url)
            now = time.time()

            # Replace references instead of mutating in-place to avoid
            # partial reads in the main thread.
            shared_state["messages"] = data.get("messages", [])
            shared_state["screen_muted"] = data.get("screen_muted", False)
            shared_state["last_update"] = now

            time.sleep(poll_interval)

    t = threading.Thread(target=poller, daemon=True)
    t.start()


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

        # Keep ticker moving while main text scrolls
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
# Active queue management
# ---------------------------------------------------------------------------

def rebuild_active_messages(active_messages, fetched_messages):
    """
    Given the current in-memory active_messages list and a fresh list of
    messages from the backend, return a new active_messages list that:

      - Keeps the existing order for messages that are still live; and
      - Appends truly new messages to the end; and
      - Drops messages that are no longer live.

    This is the key to having a stable queue where new items join the
    tail without scrambling the current order.
    """
    # Clean and de-duplicate fetched messages first
    cleaned = []
    fetched_ids = []
    for msg in fetched_messages:
        body = str(msg.get("body", "")).strip()
        if not body:
            continue
        mid = get_message_id(msg)
        if not mid:
            continue
        if mid in fetched_ids:
            continue
        fetched_ids.append(mid)
        cleaned.append(msg)

    # Preserve existing order for messages that are still live
    new_active = []
    used_ids = set()

    # Map ID -> freshest version of the message from the backend
    id_to_msg = {get_message_id(msg): msg for msg in cleaned}

    for old_msg in active_messages:
        oid = get_message_id(old_msg)
        if oid in id_to_msg and oid not in used_ids:
            new_active.append(id_to_msg[oid])
            used_ids.add(oid)

    # Append any truly new messages (that weren't already in active_messages)
    for msg in cleaned:
        mid = get_message_id(msg)
        if mid not in used_ids:
            new_active.append(msg)
            used_ids.add(mid)

    return new_active


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

    # Bright, high-contrast colors to assign per unique message.
    color_cycle = [
        graphics.Color(255, 0, 0),      # red
        graphics.Color(0, 255, 0),      # green
        graphics.Color(0, 128, 255),    # blue-ish
        graphics.Color(255, 255, 0),    # yellow
        graphics.Color(255, 0, 255),    # magenta
        graphics.Color(0, 255, 255),    # cyan
        graphics.Color(255, 165, 0),    # orange
        graphics.Color(255, 255, 255),  # white
    ]
    color_index = 0
    message_color_map = {}

    fonts = {
        "main_font": main_font,
        "main_color": graphics.Color(255, 255, 0),  # default yellow
        "ticker_font": ticker_font,
        "ticker_color": graphics.Color(200, 200, 200),
    }

    poll_interval = settings.get("poll_interval_sec", 5)
    fallback_message = settings.get("fallback_message", "^^TXT: 647-930-4995^^")
    fallback_idle = settings.get("fallback_idle_seconds", 5)
    ticker_text = settings.get("ticker_text", fallback_message)

    live_url = build_live_messages_url(settings)
    print("[Pi] Loaded settings from:", SETTINGS_FILE)
    print("[Pi] Using live messages URL:", live_url)
    print("[Pi] Poll interval (sec):", poll_interval)

    # Shared state for polling thread
    shared_state = {
        "messages": [],
        "screen_muted": False,
        "last_update": 0.0,
    }

    # Start background polling
    start_live_polling_thread(settings, live_url, poll_interval, shared_state)

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

    # Reusable offscreen canvas for idle/mute states
    offscreen_canvas = matrix.CreateFrameCanvas()

    # New stable, rotating queue
    active_messages = []   # ordered list of currently live messages
    active_index = 0       # index into active_messages
    played_cache = set()   # IDs we've notified the backend about at least once

    last_applied_update = 0.0

    while True:
        # Snapshot current polling state
        messages = shared_state["messages"]
        screen_muted = shared_state["screen_muted"]
        last_update = shared_state["last_update"]

        # If polling thread has new data, rebuild the active queue.
        if last_update != last_applied_update:
            prev_len = len(active_messages)
            active_messages = rebuild_active_messages(active_messages, messages)

            if active_messages:
                if active_index >= len(active_messages):
                    active_index = 0
            else:
                active_index = 0

            last_applied_update = last_update

            print(
                f"[Pi] Active queue size after rebuild: {len(active_messages)} "
                f"(was {prev_len})"
            )

        if screen_muted:
            # Force a full blank frame (no ticker, no messages)
            offscreen_canvas.Clear()
            offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)
            time.sleep(0.2)
            continue

        if active_messages:
            # Take the next message in the stable queue.
            msg = active_messages[active_index]
            msg_id = get_message_id(msg)
            body = str(msg.get("body", "")).strip()

            if msg_id and msg_id not in played_cache:
                # Async, non-blocking
                mark_message_played(settings, msg_id)
                played_cache.add(msg_id)

            if body:
                # Stable color per unique message (by id or body).
                key = msg_id or body
                if key not in message_color_map:
                    message_color_map[key] = color_cycle[color_index % len(color_cycle)]
                    color_index += 1
                fonts["main_color"] = message_color_map[key]

                # Scroll this message (ticker keeps moving inside scroll_text)
                scroll_text(matrix, body, settings, fonts, ticker_state)

            # Advance to the next message in the rotation.
            if active_messages:
                active_index = (active_index + 1) % len(active_messages)
            else:
                active_index = 0

        else:
            # No live messages -> only show the small bottom ticker (no full-screen scroll)
            end_idle = time.time() + fallback_idle if fallback_idle > 0 else time.time()
            while time.time() < end_idle:
                # Break early if new data has arrived
                if shared_state["last_update"] != last_applied_update:
                    break

                offscreen_canvas.Clear()
                draw_and_step_ticker(
                    offscreen_canvas,
                    settings,
                    ticker_state,
                    fonts["ticker_font"],
                    fonts["ticker_color"],
                )
                offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)
                time.sleep(settings.get("scroll_delay_sec", 0.03))


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[Pi] Exiting on Ctrl+C")
