import json
import os
import threading
import time
from pathlib import Path

import moderngl_window as mglw
from imgui_bundle import imgui
from .imgui_renderer import Renderer

from . import editor, output, presets, serve, transform, ui
from .camera import Camera
from .effects import make
from .gpu import GPU, ROOT


AUDIO_TYPES = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".aiff")


class App(mglw.WindowConfig):
    title = "BadCamera"
    gl_version = (3, 3)
    window_size = (1680, 900)
    aspect_ratio = None
    resizable = True
    vsync = True

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument("--source", default="0" if os.name == "nt" else "/dev/video0", help="webcam device, index, or a video file")
        parser.add_argument("--cam-size", default="1280x720", help="requested camera size")
        parser.add_argument("--cam-fps", type=int, default=30, help="requested camera fps")
        parser.add_argument("--out-fps", type=int, default=60, help="virtual cam / recording fps")
        parser.add_argument("--vcam-device", default=None if os.name == "nt" else "/dev/video10")
        parser.add_argument("--vcam", action="store_true", help="start the virtual cam on launch")
        parser.add_argument("--preset", default=None, help="preset name to start with")
        parser.add_argument("--open", nargs="*", default=[], help="videos, a .bcproj project or preset files to open")
        parser.add_argument("--export", default=None, help="export the opened project to this file, then quit")

    def __init__(self, **kw):
        super().__init__(**kw)
        a = self.argv
        try:
            self.wnd.set_icon(str(ROOT / "assets" / "icon.png"))
        except Exception:  # Wayland doesn't let apps set window icons; the .desktop file covers it there
            pass
        imgui.create_context()
        ui.setup()
        self.imgui = Renderer(self.wnd)
        self.g = GPU(self.ctx)
        self.cam = Camera(a.source, tuple(map(int, a.cam_size.split("x"))), a.cam_fps)
        self.cam.start()
        self.vcam, self.rec = output.VirtualCam(a.vcam_device), output.Recorder()
        self.camtex, self.last_seq, self.size = None, -1, (0, 0)
        self.mirror = self.bypass = self.want_snapshot = False
        self.message, self.save_name, self.add_i, self.fps = "", "My preset", 0, 0.0
        self.rec_t0 = 0.0
        self.tab, self.ed, self.dialog = "camera", editor.Session(), None
        self.cam_tx, self.tx_saved = editor.Tx(transform.load()), None
        self.live_steps, self.mic_device, self.mic_audio = [], None, None
        self.dragging_preview, self.last_mouse = False, (0, 0)
        self.rec_clean, self.clean_on = output.Recorder(), False
        self.lib_query, self.lib_cat, self.fs_query, self.fs_results, self.fs_key, self.fs_any = "", "All", "", [], self.load_settings().get("freesound_key", ""), False
        self.script_scene, self.reel_name, self.realism_seed, self.realism_amount, self.loud_target = 0, "Reel 2", 1, 1.0, "YouTube (-14 LUFS)"
        self.library = None
        self.queue_variant, self.tone_i, self.event_kind, self.event_amount, self.event_length = "As edited", 0, "Tracking tear", 0.7, 1.0
        self.marker_text, self.card_name, self.card_seconds = "", "Evidence tape", 3.0
        self.card_text, self.cctv_mode, self.cctv_every = editor.story.CARDS["Evidence tape"][2], "Quad split", 4.0
        self.pending_look = None
        look = self.load_settings()
        ui.set_skin(look.get("skin", "classic"), look.get("theme"))
        self.reload_presets(a.preset)
        self.start_vcam = a.vcam
        try:
            serve.publish()  # keeps the Resolve plugin's preset list current
        except OSError:
            pass
        if not self.cam.ok:
            self.message = f"No camera at {a.source}. The Editor tab still works."
        self.add_files(a.open)
        if a.export:
            self.ed.exporter = editor.Exporter(self.ed.tl, self.ed.worker, a.export)

    def load_settings(self):
        try:
            return json.loads((presets.USER / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def set_look(self, skin, palette):
        """Takes effect at the start of the next frame: colours changed mid-frame get undone when the widget that pushed them pops them."""
        self.pending_look = (skin, palette)
        self.save_settings(skin=skin, theme=palette)

    def save_settings(self, **values):
        presets.USER.mkdir(parents=True, exist_ok=True)
        (presets.USER / "settings.json").write_text(json.dumps({**self.load_settings(), **values}), encoding="utf-8")

    def background(self, work, done_message="Done"):
        """Run slow sound work off the render thread and report in the status line."""
        def run():
            try:
                self.message = work() or done_message
            except Exception as ex:
                self.message = f"Failed: {ex}"
        threading.Thread(target=run, daemon=True).start()

    def lib_items(self):
        if self.library is None:
            self.library = []

            def load():
                self.library = editor.sound.prepare_library()
                return ""
            self.background(load)
        return self.library

    def get_sound_pack(self):
        self.save_settings(freesound_key=self.fs_key)

        def progress(text):
            self.message = text

        def work():
            n = editor.sound.install_pack(self.fs_key.strip(), progress)
            self.library = editor.sound.load_index()
            return f"Sound pack: {n} new sounds"
        self.background(work)

    def add_sound_folder(self, folder):
        def work():
            self.library = editor.sound.scan_folder(folder, Path(folder).name, "Your own files, check the rights", Path(folder).name)
            return "Folder added to the library"
        self.background(work)

    def freesound_search(self):
        self.save_settings(freesound_key=self.fs_key)

        def work():
            self.fs_results = editor.sound.freesound_search(self.fs_query, self.fs_key.strip(), not self.fs_any)
            return f"{len(self.fs_results)} sounds found"
        self.background(work)

    def freesound_add(self, r):
        def work():
            e = editor.sound.freesound_add(r)
            self.library = editor.sound.load_index()
            k = editor.sound.licence_kind(e["license"])
            return f"Added \"{e['name']}\": {k['label']}"
        self.background(work)

    def switch_source(self, device):
        """Change camera or capture card without restarting."""
        self.cam.stop()
        self.cam = Camera(device, tuple(map(int, self.argv.cam_size.split("x"))), self.argv.cam_fps)
        self.cam.start()
        self.argv.source = device
        self.message = "" if self.cam.ok else f"Can't open {device}"

    def add_marker(self):
        self.ed.tl.markers.append({"t": self.ed.t, "label": self.marker_text})
        self.ed.tl.markers.sort(key=lambda m: m["t"])
        self.marker_text = ""

    def export_stems(self):
        ed = self.ed
        folder = output.stamp_path("mp4").with_suffix("")
        self.message = "Writing stems..."

        def work():
            try:
                self.message = f"Stems in {editor.export_stems(ed.tl, ed.worker, folder)}"
            except Exception as ex:
                self.message = f"Stems failed: {ex}"
        threading.Thread(target=work, daemon=True).start()

    def pick_motion(self, clip):
        def picked(paths):
            clip.motion_file = paths[0]
            self.message = "Measuring that clip's motion..."

            def done(_, error):
                self.message = error or "Motion ready"
            editor.story.extract_motion(paths[0], done)
        ui.open_dialog(self, "Pick a motion clip", ["Videos", " ".join(f"*{t}" for t in editor.VIDEO_TYPES)], picked)

    @property
    def editing(self):
        return self.tab == "editor"

    @property
    def steps(self):
        """The chain the sidebar edits: the selected clip's in the Editor, the live one in Camera."""
        if self.editing:
            return self.ed.clip.steps if self.ed.clip else []
        return self.live_steps

    @steps.setter
    def steps(self, value):
        if not self.editing:
            self.live_steps = value
        elif self.ed.clip:
            self.ed.clip.steps = value

    @property
    def tx(self):
        if self.editing:
            return self.ed.clip.tx if self.ed.clip else None
        return self.cam_tx

    def reload_presets(self, select=None):
        self.presets = presets.load_all()
        self.n_builtin = len(presets.builtin())
        names = [p["name"] for p in self.presets]
        # search from the end: a saved preset wins over a built-in of the same name
        i = len(names) - 1 - names[::-1].index(select) if select in names else 0
        if self.editing:
            self.preset_i = i
        else:
            self.load_preset(i)

    def load_preset(self, i):
        self.preset_i = i % len(self.presets)
        p = self.presets[self.preset_i]
        self.save_name = p["name"]
        clip = self.ed.clip
        if self.editing and not clip:
            self.message = "Select a clip first"
            return
        self.steps = presets.build(p)
        if self.editing:
            clip.preset_name = p["name"]
            if clip.auto_audio and p.get("audio"):
                clip.audio = p["audio"]

    def apply_to_all(self):
        clip = self.ed.clip
        for c in self.ed.tl.clips:
            if c is not clip:
                c.steps, c.preset_name = editor.clone_steps(clip.steps), clip.preset_name
                if c.auto_audio:
                    c.audio = clip.audio
        self.message = f"Applied to {len(self.ed.tl.clips)} clips"

    def add_files(self, paths):
        """Dropped or picked files: videos go on the timeline, .bcproj opens, .json imports a preset."""
        videos = []
        for p in map(str, paths):
            low = p.lower()
            try:
                if low.endswith(".bcproj"):
                    self.open_project(p)
                elif low.endswith(".json"):
                    self.reload_presets(self.import_preset(p))
                elif low.endswith(AUDIO_TYPES):
                    self.tab = "editor"
                    self.ed.add_sound(p)
                else:
                    videos.append(p)
            except (ValueError, OSError, KeyError) as ex:
                self.message = str(ex)
        if videos:
            self.tab = "editor"
            errors = self.ed.add_files(videos)
            self.message = "; ".join(errors)

    def import_preset(self, path):
        name = presets.import_file(path)
        self.message = f"Imported preset \"{name}\""
        return name

    def open_project(self, path):
        self.tab = "editor"
        missing = editor.load_project(self.ed.tl, path)
        self.ed.after_load()
        self.ed.project_path = path
        self.message = f"Missing files: {', '.join(missing)}" if missing else f"Opened {path}"

    def start_export(self):
        if not self.ed.tl.clips:
            self.message = "Add a clip first"
            return
        try:
            self.ed.pause()
            self.ed.exporter = editor.Exporter(self.ed.tl, self.ed.worker)
        except FileNotFoundError:
            self.message = "Export needs ffmpeg installed and on PATH (see README)"

    def toggle_vcam(self):
        self.vcam.toggle(*self.size, self.argv.out_fps)
        self.message = self.vcam.error or ""

    def toggle_record(self):
        if self.rec.proc:
            self.message = f"Saved {self.rec.stop()}"
            self.rec_clean.stop()
        else:
            try:
                self.rec.start(*self.size, self.argv.out_fps, self.mic_device, self.mic_audio)
            except FileNotFoundError:
                self.message = "Recording needs ffmpeg installed and on PATH (see README)"
                return
            except Exception as ex:  # microphone couldn't open
                self.message = f"Recording failed: {ex}"
                return
            self.rec_t0 = time.time()
            self.message = f"Recording to {self.rec.path}"
            if self.clean_on:  # the untouched feed alongside, so a look can be changed later
                self.rec_clean.start(*self.size, self.argv.out_fps, path=self.rec.path.with_name(self.rec.path.stem + "_clean.mp4"))

    def camera_frame(self):
        """Grab the newest camera frame and run the live chain. Also runs on the Editor tab while the virtual cam or a recording is on."""
        g = self.g
        frame, seq = self.cam.frame, self.cam.seq
        if frame is not None and seq != self.last_seq:
            h, w = frame.shape[:2]
            if self.camtex is None or self.camtex.size != (w, h):
                self.camtex = self.ctx.texture((w, h), 3, alignment=1)
                self.size = (w, h)
            self.camtex.write(frame.tobytes())
            self.last_seq = seq
        if not self.camtex:
            return None
        if self.start_vcam:
            self.start_vcam = False
            self.toggle_vcam()
        tx = self.cam_tx.v
        if transform.is_identity(tx):
            src = g.run("ingest", size=self.size, tex=self.camtex, uMirror=self.mirror, uTransformed=0)
        else:
            src = g.run("ingest", size=self.size, tex=self.camtex, uTransformed=1, uXform=transform.matrix(tx, self.size, self.size, self.mirror))
        out = src if self.bypass else presets.process(g, self.live_steps, src)
        if self.rec_clean.proc:
            self.rec_clean.write(g.read(src))
        if self.want_snapshot:
            self.want_snapshot = False
            self.message = f"Saved {output.snapshot(g.read(out))}"
        if self.vcam.cam or self.rec.proc:
            rgb = g.readback(out)
            if rgb is not None:
                self.vcam.send(rgb)
                self.rec.write(rgb)
        return out

    def poll_dialog(self):
        if self.dialog and self.dialog[0].ready(0):
            dlg, done = self.dialog
            self.dialog = None
            result = dlg.result()
            if result:
                try:
                    done(result)
                except (ValueError, OSError, KeyError) as ex:
                    self.message = str(ex)

    def on_render(self, t, frametime):
        self.fps = 0.95 * self.fps + 0.05 / max(frametime, 1e-6)
        g = self.g
        if self.pending_look:
            ui.set_skin(*self.pending_look)
            self.pending_look = None
        self.poll_dialog()
        ex = self.ed.exporter
        if ex and ex.step(g):
            self.message = ex.error or f"Exported {ex.path}"
            self.ed.exporter = None
            self.ed.job_done(ex)
            self.ed.next_job()
            if self.argv.export and not self.ed.exporter:
                print(self.message)
                self.wnd.close()
        g.begin_frame(t)
        out = None
        if not self.editing or self.vcam.cam or self.rec.proc:
            out = self.camera_frame()
        if self.editing:
            g.begin_frame(self.ed.t)
            out = self.ed.render(g, self.bypass)
            if self.want_snapshot and out:
                self.want_snapshot = False
                self.message = f"Saved {output.snapshot(g.read(out))}"
            self.ed.autosave()

        self.wnd.fbo.use()
        self.ctx.clear(*ui.gl_rgb(ui.PAGE))
        self.draw_photo_box()
        if out:
            self.draw_preview(out)

        self.wnd.fbo.use()
        imgui.new_frame()
        ui.draw(self)
        imgui.render()
        self.imgui.render(imgui.get_draw_data())
        self.save_transform()

    def save_transform(self):
        """Keep the camera transform between runs, once a drag has finished."""
        if imgui.is_mouse_down(imgui.MouseButton_.left) or self.cam_tx.v == self.tx_saved:
            return
        first = self.tx_saved is None
        self.tx_saved = dict(self.cam_tx.v)
        if not first:
            transform.save(self.cam_tx.v)

    def view_size(self):
        return self.ed.tl.format()[0] if self.editing else (self.size if self.size[0] else (16, 9))

    def fb_rect(self, r):
        """Window-space (x, y-down, w, h) -> framebuffer viewport (HiDPI-scaled, y-up)."""
        k = self.wnd.buffer_size[0] / self.wnd.size[0]
        x, y, w, h = r
        return int(x * k), int((self.wnd.size[1] - y - h) * k), int(w * k), int(h * k)

    def draw_photo_box(self):
        box, img, _ = ui.photo_rects(self.wnd.size, self.view_size(), ui.bottom(self))
        x, y, w, h = box
        self.wnd.fbo.clear(*ui.gl_rgb(ui.BORDER), viewport=self.fb_rect(box))
        self.wnd.fbo.clear(*ui.gl_rgb(ui.BOX), viewport=self.fb_rect((x + 1, y + 1, w - 2, h - 2)))
        self.wnd.fbo.clear(*ui.gl_rgb(ui.STRIP), viewport=self.fb_rect(img))  # placeholder until the camera starts

    def draw_preview(self, out):
        _, img, _ = ui.photo_rects(self.wnd.size, out.size, ui.bottom(self))
        self.g.run("copy", fbo=self.wnd.fbo, viewport=self.fb_rect(img), tex=out)

    def on_key_event(self, key, action, modifiers):
        self.imgui.key_event(key, action, modifiers)
        keys = self.wnd.keys
        if action != keys.ACTION_PRESS or imgui.get_io().want_capture_keyboard:
            return
        if self.editing:
            self.editor_key(key, modifiers)
        elif key == keys.LEFT:
            self.load_preset(self.preset_i - 1)
        elif key == keys.RIGHT:
            self.load_preset(self.preset_i + 1)
        elif key == keys.SPACE:
            self.want_snapshot = True
        elif key == keys.R:
            self.toggle_record()
        elif key == keys.V:
            self.toggle_vcam()
        elif key == keys.B:
            self.bypass = not self.bypass
        elif key == keys.F:
            self.wnd.fullscreen = not self.wnd.fullscreen

    def editor_key(self, key, modifiers):
        keys, ed = self.wnd.keys, self.ed
        step = 1 / ed.tl.format()[1]
        if key == keys.SPACE:
            ed.toggle_play()
        elif key == keys.S:
            self.split()
        elif key == keys.M:
            self.add_marker()
        elif key in (keys.DELETE, keys.BACKSPACE):
            self.delete_clip()
        elif key == keys.Z and modifiers.ctrl:
            ed.tl.redo() if modifiers.shift else ed.tl.undo()
            ed.sel = min(ed.sel, len(ed.tl.clips) - 1)
            ed.seek(ed.t)
        elif key == keys.LEFT:
            ed.seek(ed.t - step)
        elif key == keys.RIGHT:
            ed.seek(ed.t + step)
        elif key == keys.B:
            self.bypass = not self.bypass
        elif key == keys.F:
            self.wnd.fullscreen = not self.wnd.fullscreen

    def split(self):
        if not self.ed.cut():
            self.message = "Move the playhead inside the selected clip to cut it"

    def delete_clip(self):
        ed = self.ed
        if ed.sound:
            ed.tl.sounds.pop(ed.sound_sel)
            ed.sound_sel = None
        elif ed.over_sel is not None:
            ed.tl.overlays.pop(ed.over_sel)
            ed.over_sel = None
        elif self.ed.clip:
            self.ed.tl.delete(self.ed.sel)
            self.ed.sel = min(self.ed.sel, len(self.ed.tl.clips) - 1)
            self.ed.seek(self.ed.t)

    def on_resize(self, w, h):
        self.imgui.resize(w, h)

    def on_mouse_position_event(self, x, y, dx, dy):
        self.imgui.mouse_position_event(x, y, dx, dy)
        self.last_mouse = (x, y)

    def on_mouse_drag_event(self, x, y, dx, dy):
        self.imgui.mouse_drag_event(x, y, dx, dy)
        self.last_mouse = (x, y)
        if self.dragging_preview and self.tx:  # drag the picture to move it
            _, (_, _, iw, ih), _ = ui.photo_rects(self.wnd.size, self.view_size(), ui.bottom(self))
            self.tx.v["move_x"] += dx / iw
            self.tx.v["move_y"] -= dy / ih

    def over_preview(self, x, y):
        _, (ix, iy, iw, ih), _ = ui.photo_rects(self.wnd.size, self.view_size(), ui.bottom(self))
        return ix <= x < ix + iw and iy <= y < iy + ih and not imgui.get_io().want_capture_mouse

    def on_mouse_scroll_event(self, x_offset, y_offset):
        self.imgui.mouse_scroll_event(x_offset, y_offset)
        if self.tx and self.over_preview(*self.last_mouse):  # scroll over the picture to zoom it
            self.tx.v["zoom"] = min(max(self.tx.v["zoom"] * 1.08 ** y_offset, 0.1), 8.0)

    def on_mouse_press_event(self, x, y, button):
        self.imgui.mouse_press_event(x, y, button)
        self.dragging_preview = button == self.wnd.mouse.left and self.over_preview(x, y)

    def on_mouse_release_event(self, x, y, button):
        self.imgui.mouse_release_event(x, y, button)
        self.dragging_preview = False

    def on_files_dropped_event(self, x, y, paths):
        self.add_files(paths)

    def on_unicode_char_entered(self, char):
        self.imgui.unicode_char_entered(char)

    def on_close(self):
        self.ed.close()
        self.ed.clean_exit()
        self.rec.stop()
        if self.vcam.cam:
            self.vcam.cam.close()
        self.cam.stop()


def main():
    import sys
    args = sys.argv[1:]
    if "--serve" in args:  # headless engine for the Resolve plugin
        from . import serve
        serve.serve()
        return
    if "--window" not in args and "-wnd" not in args:
        args += ["--window", "glfw"]
    mglw.run_window_config(App, args=args)


if __name__ == "__main__":
    main()
