import sys
from pathlib import Path

import moderngl
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT  # writable: next to the .exe in builds
SHADERS = Path(__file__).parent / "shaders"

VERT = """#version 330
in vec2 in_pos; out vec2 uv;
void main() { uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

# Prepended to every fragment shader in shaders/.
HEADER = """#version 330
in vec2 uv; out vec4 fragColor;
uniform sampler2D tex; uniform vec2 uRes; uniform float uTime; uniform int uFrame;
float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
float hash(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
vec3 blendOverlay(vec3 b, vec3 o) { return mix(2.0 * b * o, 1.0 - 2.0 * (1.0 - b) * (1.0 - o), step(0.5, b)); }
float vdist(vec2 p) { return length((p - 0.5) * 2.0) / 1.41421; }
float vnoise(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y); }
float fbm(vec2 p) { return 0.5 * vnoise(p) + 0.25 * vnoise(p * 2.03 + 17.1) + 0.125 * vnoise(p * 4.01 + 31.7); }
#line 1
"""


class GPU:
    def __init__(self, ctx):
        self.ctx = ctx
        self.quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], "f4"))
        self.progs = {}
        self.pool, self.used = {}, {}
        self.fbos = {}
        self.assets = {}
        self.time, self.frame = 0.0, 0
        self.pbos, self.pbo_i = None, 0

    def begin_frame(self, time):
        self.time, self.frame = time, self.frame + 1
        self.used.clear()
        self.ctx.disable(moderngl.BLEND)  # imgui leaves blending on
        self.ctx.scissor = None

    def texture(self, w, h):
        t = self.ctx.texture((w, h), 4, dtype="f2")
        t.repeat_x = t.repeat_y = False
        return t

    def tmp(self, w, h):
        # shortcut: temp textures are never reused within a frame (simple, ~30 x 7MB VRAM at 720p), pool by liveness if VRAM gets tight
        lst = self.pool.setdefault((w, h), [])
        i = self.used.get((w, h), 0)
        if i == len(lst):
            lst.append(self.texture(w, h))
        self.used[(w, h)] = i + 1
        return lst[i]

    def fbo(self, tex):
        if id(tex) not in self.fbos:
            self.fbos[id(tex)] = (tex, self.ctx.framebuffer([tex]))
        return self.fbos[id(tex)][1]

    def prog(self, name):
        if name not in self.progs:
            p = self.ctx.program(vertex_shader=VERT, fragment_shader=HEADER + (SHADERS / f"{name}.glsl").read_text())
            self.progs[name] = (p, self.ctx.vertex_array(p, [(self.quad, "2f", "in_pos")]))
        return self.progs[name]

    def run(self, name, size=None, out=None, fbo=None, viewport=None, **uniforms):
        """Render shader `name` into `out` (or a fresh temp texture of `size`, or `fbo`) and return the target."""
        prog, vao = self.prog(name)
        if fbo is None:
            out = out or self.tmp(*size)
            fbo = self.fbo(out)
        fbo.use()
        old_viewport = fbo.viewport
        if viewport:
            fbo.viewport = viewport  # stored on the fbo, so restored below
        res = out.size if out else fbo.size
        unit = 0
        for k, v in {"uRes": res, "uTime": self.time, "uFrame": self.frame, **uniforms}.items():
            if k not in prog:
                continue
            if isinstance(v, (moderngl.Texture, moderngl.Texture3D)):
                v.use(unit)
                prog[k].value = unit
                unit += 1
            elif isinstance(v, np.ndarray):
                prog[k].write(v.astype("f4").tobytes())
            else:
                prog[k].value = tuple(v) if isinstance(v, list) else int(v) if isinstance(v, bool) else v
        vao.render(moderngl.TRIANGLE_STRIP)
        fbo.viewport = old_viewport
        return out or fbo

    def lut(self, name):
        key = ("lut", name)
        if key not in self.assets:
            n, data = read_cube(ROOT / "assets" / "luts" / f"{name}.cube")
            t = self.ctx.texture3d((n, n, n), 3, data.astype("f4").tobytes(), dtype="f4")
            t.repeat_x = t.repeat_y = t.repeat_z = False
            self.assets[key] = (t, n)
        return self.assets[key]

    def image(self, sub, name, repeat=False):
        key = (sub, name)
        if key not in self.assets:
            from PIL import Image
            img = Image.open(ROOT / "assets" / sub / f"{name}.png").convert("RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            t = self.ctx.texture(img.size, 4, img.tobytes())
            t.repeat_x = t.repeat_y = repeat
            self.assets[key] = t
        return self.assets[key]

    def readback(self, tex):
        """Async read via two PBOs: returns the previous frame as an RGB uint8 array (None on the first call)."""
        w, h = tex.size
        if self.pbos is None or self.pbos[0].size != w * h * 3:
            self.pbos, self.pbo_i, self.pbo_n = [self.ctx.buffer(reserve=w * h * 3) for _ in range(2)], 0, 0
        self.fbo(tex).read_into(self.pbos[self.pbo_i], components=3, alignment=1)
        self.pbo_i ^= 1  # now points at the buffer filled last frame
        self.pbo_n += 1
        if self.pbo_n < 2:
            return None
        return np.frombuffer(self.pbos[self.pbo_i].read(), np.uint8).reshape(h, w, 3)[::-1]

    def read(self, tex):
        w, h = tex.size
        return np.frombuffer(self.fbo(tex).read(components=3, alignment=1), np.uint8).reshape(h, w, 3)[::-1]


def read_cube(path):
    """Parse a .cube 3D LUT -> (size, float array of shape (n*n*n, 3), red fastest)."""
    n, rows = None, []
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "LUT_3D_SIZE":
            n = int(parts[1])
        elif parts[0][0].isdigit() or parts[0][0] in "-.":
            rows.append([float(x) for x in parts[:3]])
    data = np.array(rows, "f4")
    if n is None or len(data) != n ** 3:
        raise ValueError(f"{path}: bad .cube (size {n}, {len(data)} rows)")
    return n, data
