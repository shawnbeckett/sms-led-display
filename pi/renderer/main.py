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
    """Load a bitmap font from the rpi-rgb-led-matrix fonts directory."""
    font = graphics.Font()
    font.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/7x13.bdf")
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

    width = offscreen_canvas.width
    height = offscreen_canvas.height

    # Vertical position: baseline from bottom, adjust if needed
    text_y = height - 5

    # Static phone number text + layout
    phone_text = "647-308-4960"
    phone_x = 2      # left padding inside box
    phone_y = 11     # baseline for phone number (near top)

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

            # Clear frame
            offscreen_canvas.Clear()

            # --- STATIC PHONE NUMBER BOX (top-left, white) -------------------
            # Draw the phone text first to get its pixel width
            phone_text_width = graphics.DrawText(
                offscreen_canvas,
                font,
                phone_x,
                phone_y,
                WHITE,
                phone_text,
            )

            # Compute box coordinates with a bit of padding around text
            box_x0 = 0
            box_y0 = 0
            box_x1 = phone_x + phone_text_width + 2   # right edge with padding
            box_y1 = phone_y + 2                      # just below text

            # Clamp box so it stays on a 64x32 panel
            box_x1 = min(box_x1, width - 1)
            box_y1 = min(box_y1, height - 1)

            # Draw box outline
            graphics.DrawLine(offscreen_canvas, box_x0, box_y0, box_x1, box_y0, WHITE)  # top
            graphics.DrawLine(offscreen_canvas, box_x0, box_y1, box_x1, box_y1, WHITE)  # bottom
            graphics.DrawLine(offscreen_canvas, box_x0, box_y0, box_x0, box_y1, WHITE)  # left
            graphics.DrawLine(offscreen_canvas, box_x1, box_y0, box_x1, box_y1, WHITE)  # right

            # Redraw phone text so it’s cleanly on top of the box
            graphics.DrawText(
                offscreen_canvas,
                font,
                phone_x,
                phone_y,
                WHITE,
                phone_text,
            )

            # --- SCROLLING MESSAGE (unchanged behaviour) --------------------
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
