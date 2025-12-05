#!/usr/bin/env python3
"""
Simple status display utilities for the SMS-LED panel.

Used by startup_manager.py to:
  - Show "WiFi OK: <SSID>" briefly when normal Wi-Fi and internet are available.
  - Show a persistent "Connect to SMS-LED..." instruction when Wi-Fi is not working
    and the device has enabled its own hotspot.
"""

import time
from typing import Optional

from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics


def _create_matrix() -> RGBMatrix:
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
    options.hardware_mapping = "adafruit-hat-pwm"  # For Adafruit RGB Matrix HAT
    options.pwm_bits = 11
    options.brightness = 60
    options.gpio_slowdown = 4

    return RGBMatrix(options=options)


def _load_font() -> graphics.Font:
    """
    Load a BDF font. Path assumes rpi-rgb-led-matrix fonts are installed in the
    typical location on the Pi. Adjust this path if your fonts live elsewhere.
    """
    font = graphics.Font()
    # This path may need tweaking if your fonts are in a different directory.
    font.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/7x13.bdf")
    return font


def _scroll_message(message: str, loops: int = 1, color=None, speed_sec: float = 0.03) -> None:
    """
    Scroll a single-line message across the panel.

    Args:
        message: Text to scroll.
        loops: Number of times to fully scroll the message from right to left.
               If loops <= 0, scrolls indefinitely.
        color: Optional graphics.Color; defaults to white.
        speed_sec: Delay between scroll steps.
    """
    matrix = _create_matrix()
    offscreen_canvas = matrix.CreateFrameCanvas()
    font = _load_font()
    if color is None:
        color = graphics.Color(255, 255, 255)

    # Y position for baseline of text; tweak if you change font.
    text_y = 20

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

        offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)
        time.sleep(speed_sec)


def show_wifi_ok(ssid: Optional[str]) -> None:
    """
    Show a brief "WiFi OK: <SSID>" message on the panel, then return.

    This is intended to be called by startup_manager.py right before
    it launches the main renderer.
    """
    if ssid:
        msg = f"WiFi OK: {ssid}"
    else:
        msg = "WiFi OK"

    # Scroll the message a couple of times; adjust loops/duration as needed.
    _scroll_message(msg, loops=2, color=graphics.Color(0, 255, 0), speed_sec=0.04)


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
