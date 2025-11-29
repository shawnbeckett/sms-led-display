#!/usr/bin/env python3
import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

"""
Simple demo script: scrolls the message "SMS LED DISPLAY" across a 64x32 RGB LED
matrix (Adafruit HAT setup). Run this directly on the Pi; stop with Ctrl+C.
"""

def main():
    # --- Matrix setup (tells the library what kind of panel/HAT you have)
    options = RGBMatrixOptions()
    options.rows = 32
    options.cols = 64
    options.chain_length = 1
    options.parallel = 1
    options.gpio_mapping = "adafruit-hat"
    options.brightness = 70
    options.pwm_bits = 11
    options.drop_privileges = False

    matrix = RGBMatrix(options=options)

    # --- Font (uses a bitmap font shipped with rpi-rgb-led-matrix)
    font = graphics.Font()
    font.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/7x13.bdf")

    # --- Text to scroll
    text_color = graphics.Color(255, 255, 0)
    message = "SMS LED DISPLAY"

    offscreen_canvas = matrix.CreateFrameCanvas()
    pos = offscreen_canvas.width

    try:
        while True:
            # Clear, draw the text at the current position, then move it left
            offscreen_canvas.Clear()
            graphics.DrawText(offscreen_canvas, font, pos, 20, text_color, message)
            pos -= 1

            # Reset once the whole message has moved past the left edge
            # (font is 7 pixels wide per character)
            if pos + len(message) * 7 < 0:
                pos = offscreen_canvas.width

            time.sleep(0.03)
            offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)

    except KeyboardInterrupt:
        # On Ctrl+C, clear the display cleanly
        offscreen_canvas.Clear()
        matrix.SwapOnVSync(offscreen_canvas)

if __name__ == "__main__":
    main()
