#!/usr/bin/env python3
"""
Simple status display utilities for the SMS-LED panel.

Used by startup_manager.py to:
  - Show "WiFi OK: <SSID>" briefly when normal Wi-Fi and internet are available.
  - Show a persistent "Connect to SMS-LED..." instruction when Wi-Fi is not working
    and the device has enabled its own hotspot.
"""

import time
from typing import List, Optional

from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics


FONT_CANDIDATES = [
    "/home/pi/rpi-rgb-led-matrix/fonts/7x13.bdf",
    "/usr/local/share/rgbmatrix/fonts/7x13.bdf",
]
SMALL_FONT_CANDIDATES = [
    "/home/pi/rpi-rgb-led-matrix/fonts/5x8.bdf",
    "/usr/local/share/rgbmatrix/fonts/5x8.bdf",
    "/home/pi/rpi-rgb-led-matrix/fonts/tom-thumb.bdf",
    "/usr/local/share/rgbmatrix/fonts/tom-thumb.bdf",
]


def _log(msg: str) -> None:
    print(f"[status_display] {msg}", flush=True)


def _create_matrix() -> Optional[RGBMatrix]:
    """
    Create and return an RGBMatrix instance configured for:
      - 64x32 panel
      - 1 chain
      - Adafruit RGB Matrix HAT
    Adjust options later if you change panel layout.
    """
    options = RGBMatrixOptions()
    options.rows = 32
    options.cols = 64
    options.chain_length = 1
    options.parallel = 1
    options.hardware_mapping = "adafruit-hat"
    options.brightness = 70
    options.pwm_bits = 11
    options.drop_privileges = False

    try:
        matrix = RGBMatrix(options=options)
        return matrix
    except Exception as e:  # noqa: BLE001
        _log(f"WARN: failed to init RGBMatrix: {e}")
        return None


def _load_font(font_candidates: Optional[List[str]] = None) -> Optional[graphics.Font]:
    """
    Load a BDF font with fallback locations. Returns None if all attempts fail.
    """
    candidates = font_candidates or FONT_CANDIDATES
    font = graphics.Font()
    for path in candidates:
        try:
            font.LoadFont(path)
            _log(f"Loaded font: {path}")
            return font
        except Exception as e:  # noqa: BLE001
            _log(f"Font load failed at {path}: {e}")

    _log("WARN: could not load font from any known path; skipping text render")
    return None


def _scroll_message(
    message: str,
    loops: int = 1,
    color=None,
    speed_sec: float = 0.03,
    font_candidates: Optional[List[str]] = None,
    text_y: Optional[int] = None,
) -> None:
    """
    Scroll a single-line message across the panel.

    Args:
        message: Text to scroll.
        loops: Number of times to fully scroll the message from right to left.
               If loops <= 0, scrolls indefinitely.
        color: Optional graphics.Color; defaults to white.
        speed_sec: Delay between scroll steps.
        font_candidates: Optional list of font file paths (BDF) to try in order.
    """
    matrix = _create_matrix()
    if matrix is None:
        return

    offscreen_canvas = matrix.CreateFrameCanvas()
    font = _load_font(font_candidates)
    if font is None:
        return

    if color is None:
        color = graphics.Color(255, 255, 255)

    # Y position for baseline of text; tweak if you change font.
    text_y = 20 if text_y is None else text_y

    # Measure text width.
    text_width = graphics.DrawText(offscreen_canvas, font, 0, text_y, color, message)
    offscreen_canvas.Clear()

    # Start drawing just off the right edge.
    x_start = offscreen_canvas.width
    if loops <= 0:
        loop_target = None
    else:
        loop_target = loops

    loops_done = 0
    x = x_start

    while True:
        offscreen_canvas.Clear()
        graphics.DrawText(offscreen_canvas, font, x, text_y, color, message)
        x -= 1

        if x + text_width < 0:
            loops_done += 1
            if loop_target is not None and loops_done >= loop_target:
                break
            x = x_start

        try:
            offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)
        except Exception as e:  # noqa: BLE001
            _log(f"WARN: SwapOnVSync failed: {e}")
            break
        time.sleep(speed_sec)


def _display_message_static(message: str, duration_sec: float, color=None) -> None:
    """
    Display a single-line message without scrolling for a fixed duration.
    Clears the canvas afterward.
    """
    matrix = _create_matrix()
    if matrix is None:
        return

    offscreen_canvas = matrix.CreateFrameCanvas()
    font = _load_font()
    if font is None:
        return

    if color is None:
        color = graphics.Color(255, 255, 255)

    text_y = 20
    text_width = graphics.DrawText(offscreen_canvas, font, 0, text_y, color, message)

    # Center horizontally if room allows.
    x = max(0, (offscreen_canvas.width - text_width) // 2)
    offscreen_canvas.Clear()
    graphics.DrawText(offscreen_canvas, font, x, text_y, color, message)
    try:
        offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)
    except Exception as e:  # noqa: BLE001
        _log(f"WARN: SwapOnVSync failed for static display: {e}")
        return

    time.sleep(duration_sec)

    # Clear after showing.
    offscreen_canvas.Clear()
    try:
        matrix.SwapOnVSync(offscreen_canvas)
    except Exception as e:  # noqa: BLE001
        _log(f"WARN: SwapOnVSync failed during clear: {e}")


def show_wifi_ok(ssid: Optional[str]) -> None:
    """
    Show a brief "WIFI OK: <SSID>" message on the panel, scrolling once.

    This is intended to be called by startup_manager.py right before
    it launches the main renderer.
    """
    if ssid:
        msg = f"WIFI OK: {ssid}"
    else:
        msg = "WIFI OK"

    # Scroll once across the panel; adjust duration as needed.
    _scroll_message(
        msg,
        loops=1,
        color=graphics.Color(0, 255, 0),
        speed_sec=0.02,
        font_candidates=SMALL_FONT_CANDIDATES + FONT_CANDIDATES,
        text_y=14,
    )


def show_wifi_setup_instructions() -> None:
    """
    Show a persistent message instructing the user to connect to the SMS-LED
    hotspot and visit the local Wi-Fi configuration page.

    This is intended to run "forever" while the device is in AP mode.
    """
    msg = "No WiFi. Connect to SMS-LED and go to http://192.168.4.1"
    # Scroll indefinitely until the device reboots or this process is killed.
    _scroll_message(msg, loops=0, color=graphics.Color(255, 165, 0), speed_sec=0.04)


if __name__ == "__main__":
    # Simple manual test:
    #   python3 status_display.py ok
    #   python3 status_display.py setup
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
    if mode == "ok":
        ssid = sys.argv[2] if len(sys.argv) > 2 else None
        show_wifi_ok(ssid)
    else:
        show_wifi_setup_instructions()
