import os
import time

import moderngl_window as mglw
from imgui_bundle import imgui
from .imgui_renderer import Renderer

from . import output, presets, ui
from .camera import Camera
from .gpu import GPU, ROOT


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
        self.reload_presets(a.preset)
        self.start_vcam = a.vcam

    def reload_presets(self, select=None):
        self.presets = presets.load_all()
        self.n_builtin = len(presets.builtin())
        names = [p["name"] for p in self.presets]
        self.load_preset(names.index(select) if select in names else 0)

    def load_preset(self, i):
        self.preset_i = i % len(self.presets)
        self.steps = presets.build(self.presets[self.preset_i])
        self.save_name = self.presets[self.preset_i]["name"]

    def toggle_vcam(self):
        self.vcam.toggle(*self.size, self.argv.out_fps)
        self.message = self.vcam.error or ""

    def toggle_record(self):
        if self.rec.proc:
            self.message = f"Saved {self.rec.stop()}"
        else:
            try:
                self.rec.start(*self.size, self.argv.out_fps)
            except FileNotFoundError:
                self.message = "Recording needs ffmpeg installed and on PATH (see README)"
                return
            self.rec_t0 = time.time()
            self.message = f"Recording to {self.rec.path}"

    def on_render(self, t, frametime):
        self.fps = 0.95 * self.fps + 0.05 / max(frametime, 1e-6)
        g = self.g
        g.begin_frame(t)
        frame, seq = self.cam.frame, self.cam.seq
        if frame is not None and seq != self.last_seq:
            h, w = frame.shape[:2]
            if self.camtex is None or self.camtex.size != (w, h):
                self.camtex = self.ctx.texture((w, h), 3, alignment=1)
                self.size = (w, h)
            self.camtex.write(frame.tobytes())
            self.last_seq = seq

        self.wnd.fbo.use()
        self.ctx.clear(*ui.gl_rgb(ui.PAGE))
        self.draw_photo_box()
        if self.camtex:
            if self.start_vcam:
                self.start_vcam = False
                self.toggle_vcam()
            src = g.run("ingest", size=self.size, tex=self.camtex, uMirror=self.mirror)
            out = src if self.bypass else presets.process(g, self.steps, src)
            if self.want_snapshot:
                self.want_snapshot = False
                self.message = f"Saved {output.snapshot(g.read(out))}"
            if self.vcam.cam or self.rec.proc:
                rgb = g.readback(out)
                if rgb is not None:
                    self.vcam.send(rgb)
                    self.rec.write(rgb)
            self.draw_preview(out)

        self.wnd.fbo.use()
        imgui.new_frame()
        ui.draw(self)
        imgui.render()
        self.imgui.render(imgui.get_draw_data())

    def fb_rect(self, r):
        """Window-space (x, y-down, w, h) -> framebuffer viewport (HiDPI-scaled, y-up)."""
        k = self.wnd.buffer_size[0] / self.wnd.size[0]
        x, y, w, h = r
        return int(x * k), int((self.wnd.size[1] - y - h) * k), int(w * k), int(h * k)

    def draw_photo_box(self):
        box, img, _ = ui.photo_rects(self.wnd.size, self.size if self.size[0] else (16, 9))
        x, y, w, h = box
        self.wnd.fbo.clear(*ui.gl_rgb(ui.BORDER), viewport=self.fb_rect(box))
        self.wnd.fbo.clear(1.0, 1.0, 1.0, viewport=self.fb_rect((x + 1, y + 1, w - 2, h - 2)))
        self.wnd.fbo.clear(*ui.gl_rgb(ui.STRIP), viewport=self.fb_rect(img))  # placeholder until the camera starts

    def draw_preview(self, out):
        _, img, _ = ui.photo_rects(self.wnd.size, out.size)
        self.g.run("copy", fbo=self.wnd.fbo, viewport=self.fb_rect(img), tex=out)

    def on_key_event(self, key, action, modifiers):
        self.imgui.key_event(key, action, modifiers)
        keys = self.wnd.keys
        if action != keys.ACTION_PRESS or imgui.get_io().want_capture_keyboard:
            return
        if key == keys.LEFT:
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

    def on_resize(self, w, h):
        self.imgui.resize(w, h)

    def on_mouse_position_event(self, x, y, dx, dy):
        self.imgui.mouse_position_event(x, y, dx, dy)

    def on_mouse_drag_event(self, x, y, dx, dy):
        self.imgui.mouse_drag_event(x, y, dx, dy)

    def on_mouse_scroll_event(self, x_offset, y_offset):
        self.imgui.mouse_scroll_event(x_offset, y_offset)

    def on_mouse_press_event(self, x, y, button):
        self.imgui.mouse_press_event(x, y, button)

    def on_mouse_release_event(self, x, y, button):
        self.imgui.mouse_release_event(x, y, button)

    def on_unicode_char_entered(self, char):
        self.imgui.unicode_char_entered(char)

    def on_close(self):
        self.rec.stop()
        if self.vcam.cam:
            self.vcam.cam.close()
        self.cam.stop()


def main():
    import sys
    args = sys.argv[1:]
    if "--window" not in args and "-wnd" not in args:
        args += ["--window", "glfw"]
    mglw.run_window_config(App, args=args)


if __name__ == "__main__":
    main()
