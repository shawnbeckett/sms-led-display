#!/usr/bin/env python3
import os
import time
from pathlib import Path

from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics


# --- Configuration -----------------------------------------------------------

# Path to the message file (lives alongside this script in pi/renderer/)
MESSAGE_FILE = Path(__file__).parent / "message.txt"

# How often (in seconds) to check for updates to message.txt
RELOAD_INTERVAL_SEC = 1.0

# Delay between scroll steps (smaller = faster scroll)
SCROLL_DELAY_SEC = 0.03

# Simple rainbow palette to cycle through over time
RAINBOW_COLORS = [
    graphics.Color(255, 0, 0),      # red
    graphics.Color(255, 127, 0),    # orange
    graphics.Color(255, 255, 0),    # yellow
    graphics.Color(0, 255, 0),      # green
    graphics.Color(0, 0, 255),      # blue
    graphics.Color(75, 0, 130),     # indigo
    graphics.Color(148, 0, 211),    # violet
]

WHITE = graphics.Color(255, 255, 255)


def create_matrix():
    """Initialize and return the RGBMatrix with options tuned to your panel/HAT."""
    options = RGBMatrixOptions()
    options.rows = 32
    options.cols = 64
    options.chain_length = 1
    options.parallel = 1
    options.hardware_mapping = "adafruit-hat"
    options.brightness = 70
    options.pwm_bits = 11
    options.drop_privileges = False

    return RGBMatrix(options=options)


def load_font():
    """Load the main scrolling-text font."""
    font = graphics.Font()
    font.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/7x13.bdf")
    return font


def load_small_font():
    """Load a very small, blocky font for the static phone number box."""
    font = graphics.Font()
    font.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/4x6.bdf")
    return font


def read_message_from_file():
    """
    Read and normalize the message from MESSAGE_FILE.

    Returns:
        str | None:
            - str with the message if there is non-whitespace content
            - None if file is missing, unreadable, or only whitespace
    """
    try:
        raw = MESSAGE_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        # Any other read error: treat as "no message"
        return None

    msg = raw.strip()
    if not msg:
        return None

    # For now, keep it single-line; ignore newlines if present
    # (you can extend to multi-line later)
    return " ".join(msg.splitlines())


def main():
    matrix = create_matrix()
    offscreen_canvas = matrix.CreateFrameCanvas()
    font = load_font()
    header_font = load_small_font()

    width = offscreen_canvas.width
    height = offscreen_canvas.height

    # Vertical position for scrolling text: baseline from bottom
    text_y = height - 5

    # --- Static phone number box layout (small region in upper-left) ---------
    # Use a two-line layout so the box stays compact
    phone_line1 = "647-308"
    phone_line2 = "4960"

    phone_x = 2         # left padding
    phone_y1 = 6        # baseline for first line (4x6 font)
    phone_y2 = phone_y1 + 7   # second line: 6px font height + 1px spacing

    # Precompute width for the box using line 1
    temp_width = graphics.DrawText(
        offscreen_canvas,
        header_font,
        phone_x,
        phone_y1,
        WHITE,
        phone_line1,
    )
    phone_text_width = temp_width if temp_width else 0
    offscreen_canvas.Clear()

    # Compute box bounds
    box_x0 = 0
    box_y0 = 0
    box_x1 = min(phone_x + phone_text_width + 2, width - 1)
    box_y1 = phone_y2 + 2   # padding under second line

    # State for message + file reload
    current_message = None
    last_mtime = None
    last_reload_time = 0.0

    # Scroll position
    pos_x = width

    # Color cycling state
    color_index = 0

    try:
        while True:
            now = time.time()

            # --- Periodically reload message.txt -----------------------------
            if now - last_reload_time >= RELOAD_INTERVAL_SEC:
                last_reload_time = now

                try:
                    mtime = os.path.getmtime(MESSAGE_FILE)
                except OSError:
                    mtime = None

                # Only re-read if file changed or if we never had a message
                if mtime != last_mtime:
                    last_mtime = mtime
                    new_message = read_message_from_file()

                    # If message changed (including to/from None), reset scroll
                    if new_message != current_message:
                        current_message = new_message
                        pos_x = width  # restart from right edge

            # --- Drawing / scrolling logic -----------------------------------
            if current_message is None:
                # Empty or missing file: clear the panel and idle
                matrix.Clear()
                time.sleep(0.1)
                continue

            # Advance rainbow color each frame
            color_index = (color_index + 1) % len(RAINBOW_COLORS)
            text_color = RAINBOW_COLORS[color_index]

            # Clear frame for new draw
            offscreen_canvas.Clear()

            # --- STATIC PHONE NUMBER BOX (top-left, small 4x6 font) -----------------
            # Box outline
            graphics.DrawLine(offscreen_canvas, box_x0, box_y0, box_x1, box_y0, WHITE)
            graphics.DrawLine(offscreen_canvas, box_x0, box_y1, box_x1, box_y1, WHITE)
            graphics.DrawLine(offscreen_canvas, box_x0, box_y0, box_x0, box_y1, WHITE)
            graphics.DrawLine(offscreen_canvas, box_x1, box_y0, box_x1, box_y1, WHITE)

            # Phone number text (two lines)
            graphics.DrawText(offscreen_canvas, header_font, phone_x, phone_y1, WHITE, phone_line1)
            graphics.DrawText(offscreen_canvas, header_font, phone_x, phone_y2, WHITE, phone_line2)

            # --- SCROLLING MESSAGE (same behaviour as before) ----------------
            text_length = graphics.DrawText(
                offscreen_canvas,
                font,
                pos_x,
                text_y,
                text_color,
                current_message,
            )

            # Move left by one pixel
            pos_x -= 1

            # If text has fully scrolled off to the left, reset to right edge
            if pos_x + text_length < 0:
                pos_x = width

            offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)
            time.sleep(SCROLL_DELAY_SEC)

    except KeyboardInterrupt:
        # Graceful exit: clear the display
        matrix.Clear()


if __name__ == "__main__":
    main()
