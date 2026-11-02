"""Drive the real UI headlessly with simulated mouse and keyboard input, then check what happened.

Run from the project root: python -m tests.test_ui
"""
import json
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import moderngl_window as mglw
import numpy as np
from imgui_bundle import imgui

from badcamera import editor, output, presets, ui
from badcamera.__main__ import App
from tests.test_editor import make_clip, quiet_tone

TMP = Path(tempfile.mkdtemp())
editor.AUTOSAVE = TMP / "autosave.bcproj"
A, B = str(TMP / "a.mp4"), str(TMP / "b.mp4")
make_clip(A, dur=4, tone=440)
make_clip(B, dur=2, tone=880)


class Drive(App):
    """A script of steps, one per few frames. Each step is a function that acts or asserts."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.script, self.wait_until = self.steps_(), 0

    def mouse(self, x, y, down=None):
        io = imgui.get_io()
        io.add_mouse_pos_event(x, y)
        if down is not None:
            io.add_mouse_button_event(0, down)

    def clip_x(self, i, frac=0.5):
        """Window x of a position within clip i on the timeline."""
        w = self.wnd.size[0]
        left, width = ui.MARGIN + 10, w - ui.SIDE_W - 3 * ui.MARGIN - 20
        c, a, b = self.ed.tl.layout()[i]
        return left + (a + (b - a) * frac) / self.ed.tl.duration * width

    def video_y(self):
        return self.wnd.size[1] - ui.TIMELINE_H - ui.MARGIN + 10 + 28 + ui.RULER_H + ui.OVER_H + 20

    def steps_(self):
        ed = self.ed
        # Drop: videos go to the Editor. A dropped preset file is imported rather than treated as a video.
        self.on_files_dropped_event(0, 0, [A, B])
        assert self.tab == "editor" and len(ed.tl.clips) == 2
        yield 30
        # Click a clip to select it.
        y = self.video_y()
        self.mouse(self.clip_x(0), y)
        yield 3
        self.mouse(self.clip_x(0), y, True)
        yield 3
        self.mouse(self.clip_x(0), y, False)
        yield 3
        assert ed.sel == 0, ed.sel
        # Drag clip 0 past clip 1: reorders.
        first = ed.tl.clips[0].path
        self.mouse(self.clip_x(0, 0.3), y)
        yield 3
        self.mouse(self.clip_x(0, 0.3), y, True)
        yield 3
        self.mouse(self.clip_x(1, 0.9), y)
        yield 4
        self.mouse(self.clip_x(1, 0.9), y, False)
        yield 4
        assert ed.tl.clips[1].path == first, "drag didn't reorder"
        # Drag a clip's right edge left: trims it.
        before = ed.tl.clips[1].length
        x = self.clip_x(1, 1.0) - 2
        self.mouse(x, y)
        yield 3
        self.mouse(x, y, True)
        yield 3
        self.mouse(x - 120, y)
        yield 4
        self.mouse(x - 120, y, False)
        yield 4
        assert ed.tl.clips[1].length < before - 0.3, (ed.tl.clips[1].length, before)
        # Ruler click moves the playhead.
        self.mouse(self.clip_x(1, 0.0) + 40, y - 30)
        yield 3
        self.mouse(self.clip_x(1, 0.0) + 40, y - 30, True)
        yield 3
        self.mouse(self.clip_x(1, 0.0) + 40, y - 30, False)
        yield 3
        assert ed.t > 1.0, ed.t
        # S cuts, Ctrl+Z undoes, Delete removes.
        keys = type("K", (), dict(SPACE=1, S=2, Z=3, DELETE=4, BACKSPACE=5, LEFT=6, RIGHT=7, B=8, F=9, M=10))  # the headless window has no key codes
        type(self.wnd).keys = keys
        n = len(ed.tl.clips)
        self.editor_key(keys.S, type("M", (), {"ctrl": False, "shift": False}))
        yield 3
        assert len(ed.tl.clips) == n + 1
        self.editor_key(keys.Z, type("M", (), {"ctrl": True, "shift": False}))
        yield 3
        assert len(ed.tl.clips) == n
        self.editor_key(keys.Z, type("M", (), {"ctrl": True, "shift": True}))
        yield 3
        assert len(ed.tl.clips) == n + 1
        self.editor_key(keys.DELETE, type("M", (), {"ctrl": False, "shift": False}))
        yield 3
        assert len(ed.tl.clips) == n
        # Preset click in Editor applies to the clip only, and picks matching sound.
        i = next(k for k, p in enumerate(self.presets) if p["name"] == "VHS")
        self.load_preset(i)
        yield 3
        assert ed.clip.preset_name == "VHS" and ed.clip.audio == "VHS linear SP" and not self.live_steps == ed.clip.steps
        # Play advances the clock, and pausing stops it.
        sys.modules["sounddevice"] = None  # stay silent: this runs the no-audio-device path
        ed.seek(0)
        ed.play()
        t0 = time.time()
        while time.time() - t0 < 1.0:
            yield 1
        played, wall = ed.t, time.time() - t0
        ed.pause()
        del sys.modules["sounddevice"]
        assert abs(played - wall) < 0.1, (played, wall)
        # The audio callback fills buffers from the timeline.
        ed.worker.wait(ed.tl.audio_keys())
        ed.tl.clips[0].audio = "Original"
        ed.seek(1.02)  # the first beep in clip 0
        out = np.zeros((2048, 2), "f4")
        ed.audio_out(out, 2048, None, None)
        assert np.abs(out).max() > 0.1 and ed.sample == int(1.02 * 48000) + 2048
        # A clip's transform really changes the picture.
        g = self.g
        ed.seek(0.5)
        yield 25
        g.begin_frame(0.5)
        before_frame = g.read(ed.render(g)).copy()
        shown = ed.tl.clips[0]
        shown.tx.v["rotate"] = 90.0
        g.begin_frame(0.5)
        after = g.read(ed.render(g))
        assert np.abs(before_frame.astype(float) - after.astype(float)).mean() > 0.5
        shown.tx.v["rotate"] = 0.0
        # Every track cuts and trims: a sound clip, by real mouse drag on its edge, then a cut at the playhead.
        tone = quiet_tone("Room tone", 8)
        snd = ed.add_sound(tone, 0.5, 1)
        snd.end = 2.0
        yield 3
        lanes_y = self.wnd.size[1] - ui.TIMELINE_H - ui.MARGIN + 10 + 28 + ui.RULER_H + ui.OVER_H + ui.VIDEO_H + ui.WAVE_H + 4
        y2 = lanes_y + ui.SOUND_H + 12
        w_ = self.wnd.size[0] - ui.SIDE_W - 3 * ui.MARGIN - 20
        left = ui.MARGIN + 10
        xr = left + (snd.at + snd.length) / ed.tl.duration * w_ - 1
        self.mouse(xr, y2)
        yield 3
        self.mouse(xr, y2, True)
        yield 3
        self.mouse(xr - 60, y2)
        yield 3
        self.mouse(xr - 60, y2, False)
        yield 3
        assert snd.end < 2.0 - 0.1, ("edge drag should trim a sound", snd.end)
        ed.seek(snd.at + snd.length / 2)
        ed.sound_sel = ed.tl.sounds.index(snd)
        self.split()
        assert len(ed.tl.sounds) == 2, "cut should work on the sound track"
        self.delete_clip()
        assert len(ed.tl.sounds) == 1
        ed.tl.sounds.clear()
        ed.sound_sel = None
        # Camera tab: dragging the picture moves it, scrolling zooms it.
        self.tab = "camera"
        yield 3
        _, (ix, iy, iw, ih), _ = ui.photo_rects(self.wnd.size, self.view_size(), 0)
        self.mouse(ix + iw / 2, iy + ih / 2)
        self.on_mouse_position_event(ix + iw / 2, iy + ih / 2, 0, 0)
        yield 3
        self.on_mouse_press_event(ix + iw / 2, iy + ih / 2, self.wnd.mouse.left)
        self.on_mouse_drag_event(ix + iw / 2 + iw / 4, iy + ih / 2, iw / 4, 0)
        self.on_mouse_release_event(ix + iw / 2 + iw / 4, iy + ih / 2, self.wnd.mouse.left)
        assert abs(self.cam_tx.v["move_x"] - 0.25) < 1e-6, self.cam_tx.v
        self.on_mouse_scroll_event(0, 3)
        assert self.cam_tx.v["zoom"] > 1.2
        self.cam_tx.v.update(editor.transform.new())
        # Studio layout: the page bar really switches workspaces and panels, and every page draws.
        self.tab = "editor"
        # Switching with the real link, mid-frame. The window colour must be the Studio one afterwards.
        ui.set_skin("classic")
        yield 3
        self.set_look("studio", "studio")
        ui.imgui.get_style().set_color_(ui.imgui.Col_.window_bg, ui.rgb("#ffffff"))  # what a pop restoring the old colour leaves behind
        yield 3
        bg = ui.imgui.get_style().color_(ui.imgui.Col_.window_bg)
        assert bg.x < 0.3, ("Studio panels came up light", bg.x)
        w, h = self.wnd.size
        cell_x = (w - 104 * len(ui.PAGES)) / 2
        for i, name in enumerate(ui.PAGES):
            x, y = cell_x + 104 * i + 50, h - 18
            self.mouse(x, y)
            yield 2
            self.mouse(x, y, True)
            yield 2
            self.mouse(x, y, False)
            yield 3
            assert self.tab == ("camera" if name == "Camera" else "editor"), name
            if name != "Camera":
                assert ui.page == name
        ui.page = "Library"
        yield 30
        ui.set_skin("classic")
        for palette in ("dark", "light"):
            self.set_look("classic", palette)
            yield 2
        assert (presets.USER / "settings.json").exists()
        (presets.USER / "settings.json").unlink()
        print("all UI checks passed")

    def on_render(self, t, frametime):
        super().on_render(t, frametime)
        if self.wait_until > 0:
            self.wait_until -= 1
            return
        try:
            self.wait_until = next(self.script)
        except StopIteration:
            self.wnd.close()


def test_recording_speed():
    """Render at about 20 fps into a 60 fps file: the file must still last as long as the real time that passed."""
    r = output.Recorder()
    r.start(320, 240, 60)
    frame = np.zeros((240, 320, 3), np.uint8)
    t0 = time.time()
    while time.time() - t0 < 3:
        r.write(frame)
        time.sleep(0.05)
    path = r.stop()
    r.saved.wait(10)
    info = output.probe(path)
    print(f"recorded {info['duration']:.2f}s of {time.time() - t0:.2f}s at about 20 fps")
    assert abs(info["duration"] - 3) < 0.2, info
    path.unlink()


def test_mic_sync():
    """A mic track that starts 200 ms late, with a beep that belongs at 1 s, must land on the flash at 1 s."""
    d = Path(tempfile.mkdtemp())

    class Late:
        path, offset = d / "mic.wav", 0.2

        def stop(self):
            pass

    t = np.arange(int(2.8 * output.SR)) / output.SR
    tone = (0.5 * np.sin(2 * np.pi * 440 * t) * ((t > 0.8) & (t < 0.9)) * 32767).astype("i2")
    with wave.open(str(Late.path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(output.SR)
        w.writeframes(tone.tobytes())
    r = output.Recorder()
    r.start(320, 240, 30)
    for i in range(90):
        r.proc.stdin.write(np.full((240, 320, 3), 255 if 30 <= i < 33 else 0, np.uint8).tobytes())
    r.finished_mic = Late()
    r.q.put(None)
    r.proc = None
    r.saved.wait(15)
    ff = output.ffmpeg()
    v = np.frombuffer(subprocess.run([ff, "-loglevel", "error", "-i", str(r.path), "-vf", "scale=8:8", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                                     capture_output=True).stdout, "u1").reshape(-1, 8, 8).mean((1, 2))
    a = np.frombuffer(subprocess.run([ff, "-loglevel", "error", "-i", str(r.path), "-vn", "-ac", "1", "-ar", str(output.SR), "-f", "s16le", "-"],
                                     capture_output=True).stdout, "i2").astype("f8") / 32768
    flash = np.flatnonzero(v > 128)[0] / 30
    beep = np.flatnonzero(np.convolve(np.abs(a), np.ones(240) / 240, "same") > 0.1)[0] / output.SR
    print(f"mic sync: flash {flash:.3f}s, beep {beep:.3f}s")
    assert abs(flash - beep) < 0.03, (flash, beep)
    r.path.unlink()


def test_upgrade():
    user = json.loads((Path.home() / "BadCamera-backup-2026-11-01/presets-user/betterroadkill2.json").read_text())
    assert presets.uses_old_vhs(user)
    before = json.dumps(user)
    name = presets.upgrade_copy(user)
    made = next(p for p in presets.load_all() if p["name"] == name)
    assert json.dumps(user) == before and name == "BetterRoadkill2 (New Tape)"
    assert not presets.uses_old_vhs(made) and any(s["type"] == "tape" for s in made["steps"])
    presets.build(made)
    (presets.USER / "betterroadkill2_new_tape.json").unlink()


test_recording_speed()
test_mic_sync()
test_upgrade()
print("ok recording, upgrade copy")
mglw.run_window_config(Drive, args=["--window", "headless", "--size", "1600x900", "--source", "/dev/null"])
