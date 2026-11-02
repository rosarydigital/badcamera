"""Render the full app (UI + live camera) off-screen and save a PNG of the window.

Run: ~/.local/share/badcamera/venv/bin/python -m tests.screenshot OUT.png [app options...]
"""
import sys
import time

import moderngl_window as mglw
from PIL import Image

from badcamera.__main__ import App
from badcamera import editor, ui
from tests.test_editor import quiet_tone

if "--expand" in sys.argv:  # open every effect so the slider layout shows up in the shot
    sys.argv.remove("--expand")
    _header = ui.imgui.collapsing_header
    ui.imgui.collapsing_header = lambda label, flags=0: _header(label, flags | ui.imgui.TreeNodeFlags_.default_open)

CLIPS = []
while "--clip" in sys.argv:  # open the Editor tab with these videos on the timeline
    i = sys.argv.index("--clip")
    CLIPS.append(sys.argv[i + 1])
    del sys.argv[i:i + 2]
DARK = "--dark" in sys.argv
if DARK:
    sys.argv.remove("--dark")
STUDIO = next((a.split("=")[1] for a in sys.argv if a.startswith("--studio=")), None)
if STUDIO:
    sys.argv = [a for a in sys.argv if not a.startswith("--studio=")]
OUT = sys.argv[1]


class Shot(App):
    def on_render(self, t, frametime):
        if CLIPS and not self.ed.tl.clips:
            self.add_files(CLIPS)
            self.ed.seek(1.0)
            self.load_preset(next(i for i, p in enumerate(self.presets) if p["name"] == "VHS"))
            if DARK:
                ui.set_theme("dark")
            if STUDIO:
                ui.set_skin("studio")
                ui.page = STUDIO
            if len(CLIPS) > 1:
                self.ed.tl.clips[0].trans = "Crossfade"
            self.ed.tl.markers.append({"t": 1.5, "label": "Scene 12"})
            self.ed.tl.events.append({"t": 4.0, "d": 1.0, "kind": "Tracking tear", "amount": 0.8})
            self.ed.tl.age_end = 0.7
            self.ed.t = 1.0
            self.ed.add_overlay(CLIPS[-1])
            self.ed.add_sound(quiet_tone("Room tone"), 0.5, 0)
            self.ed.add_sound(quiet_tone("Wind outside"), 2.0, 1)
            self.ed.over_sel = None
            editor.set_key(self.ed.clip.tx, "zoom", 0.5, 1.0)
        super().on_render(t, frametime)
        time.sleep(1 / 60)  # like vsync in a real window, which gives background threads room to run
        if t > 4 and (self.camtex or CLIPS):  # let the camera warm up and the UI settle
            fbo = self.wnd.fbo
            Image.frombytes("RGB", fbo.size, fbo.read(components=3)).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(OUT)
            self.wnd.close()


mglw.run_window_config(Shot, args=["--window", "headless", "--size", "1600x900"] + sys.argv[2:])
