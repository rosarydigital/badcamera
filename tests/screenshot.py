"""Render the full app (UI + live camera) off-screen and save a PNG of the window.

Run: ~/.local/share/badcamera/venv/bin/python -m tests.screenshot OUT.png [app options...]
"""
import sys

import moderngl_window as mglw
from PIL import Image

from badcamera.__main__ import App
from badcamera import ui

if "--expand" in sys.argv:  # open every effect so the slider layout shows up in the shot
    sys.argv.remove("--expand")
    _header = ui.imgui.collapsing_header
    ui.imgui.collapsing_header = lambda label, flags=0: _header(label, flags | ui.imgui.TreeNodeFlags_.default_open)

OUT = sys.argv[1]


class Shot(App):
    def on_render(self, t, frametime):
        super().on_render(t, frametime)
        if t > 4 and self.camtex:  # let the camera warm up and the UI settle
            fbo = self.wnd.fbo
            Image.frombytes("RGB", fbo.size, fbo.read(components=3)).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(OUT)
            self.wnd.close()


mglw.run_window_config(Shot, args=["--window", "headless", "--size", "1600x900"] + sys.argv[2:])
