"""Effect steps. Each step declares its params (the UI is generated from them) and renders with GPU.run."""
import math
import random
import time
from dataclasses import dataclass

import numpy as np

from . import text
from .gpu import ROOT

REGISTRY = {}
rng = random.Random()  # effect randomness; export reseeds it so renders repeat


def assets(sub, ext):
    return sorted(p.stem for p in (ROOT / "assets" / sub).glob(f"*{ext}"))


@dataclass
class P:
    key: str
    default: object
    lo: float = 0.0
    hi: float = 1.0
    options: object = None  # list, or callable returning a list, for enum params
    color: bool = False

    @property
    def kind(self):
        d = self.default
        if isinstance(d, bool):
            return "bool"
        if isinstance(d, int):
            return "int"
        if isinstance(d, float):
            return "float"
        if isinstance(d, list):
            return "color" if self.color else "vec3"
        return "enum" if self.options is not None else "text"

    def choices(self):
        return self.options() if callable(self.options) else self.options


class Effect:
    type = ""
    params = []
    styles = {}

    def __init__(self, enabled=True, **values):
        self.enabled = enabled
        self.error = None
        self.v = {p.key: list(p.default) if isinstance(p.default, list) else p.default for p in self.params}
        for p in self.params:
            if p.key in values:  # coerce preset JSON (e.g. 1 for a float) to the param's type
                d = p.default
                self.v[p.key] = [float(x) for x in values[p.key]] if isinstance(d, list) else type(d)(values[p.key])

    def apply(self, g, tex):
        raise NotImplementedError

    def to_json(self):
        return {"type": self.type, "enabled": self.enabled, "params": self.v}


def effect(cls):
    REGISTRY[cls.type] = cls
    return cls


def make(type, params=None, enabled=True):
    return REGISTRY[type](enabled, **(params or {}))


# ---- helpers ----

def shrink(g, tex, size):
    """Downscale by successive halvings so large factors don't alias."""
    while tex.width >= 2 * size[0] and tex.height >= 2 * size[1] and (tex.width // 2, tex.height // 2) != size:
        tex = g.run("copy", size=(tex.width // 2, tex.height // 2), tex=tex)
    return tex if tex.size == size else g.run("copy", size=size, tex=tex)


def blur(g, tex, sigma):
    t = g.run("blur", size=tex.size, tex=tex, uDir=(1.0, 0.0), uSigma=sigma)
    return g.run("blur", size=tex.size, tex=t, uDir=(0.0, 1.0), uSigma=sigma)


def down(tex, factor):
    return max(1, tex.width // factor), max(1, tex.height // factor)


class Temporal(Effect):
    """Base for steps that keep their own textures between frames."""
    size = None

    def textures(self, g, tex, n):
        if self.size != tex.size:
            self.size, self.n, self.hist = tex.size, 0, [g.texture(*tex.size) for _ in range(n)]
            return True
        return False


BLENDS = ["screen", "add", "overlay", "multiply"]

# ---- core steps (mirroring the digicamfx pipeline) ----


@effect
class ColorGrade(Effect):
    type = "color_grade"
    params = [P("exposure", 0.0, -3, 3), P("contrast", 0.0, -1, 1), P("saturation", 0.0, -1, 1),
              P("temperature", 0.0, -1, 1), P("tint", 0.0, -1, 1),
              P("lift", [0.0, 0.0, 0.0], -0.5, 0.5), P("gamma", [0.0, 0.0, 0.0], -0.9, 1.0), P("gain", [0.0, 0.0, 0.0], -0.5, 0.5)]

    def apply(self, g, tex):
        v = self.v
        return g.run("grade", size=tex.size, tex=tex, uExposure=v["exposure"], uContrast=v["contrast"], uSaturation=v["saturation"],
                     uTemp=v["temperature"], uTint=v["tint"], uLift=v["lift"], uGamma=v["gamma"], uGain=v["gain"])


@effect
class Lut(Effect):
    type = "lut"
    params = [P("lut", "ccd", options=lambda: assets("luts", ".cube")), P("intensity", 1.0)]

    def apply(self, g, tex):
        lut, n = g.lut(self.v["lut"])
        return g.run("lut", size=tex.size, tex=tex, uLut=lut, uSize=float(n), uIntensity=self.v["intensity"])


@effect
class GaussianBlur(Effect):
    type = "gaussian_blur"
    params = [P("sigma", 1.0, 0.1, 20), P("downsample", 1, 1, 16)]

    def apply(self, g, tex):
        return g.run("copy", size=tex.size, tex=blur(g, shrink(g, tex, down(tex, self.v["downsample"])), self.v["sigma"]))


@effect
class Bloom(Effect):
    type = "bloom"
    params = [P("amount", 1.0, 0, 2), P("tint", [1.0, 1.0, 1.0], color=True), P("gamma", 3.0, 0.5, 8),
              P("sigma", 4.0, 0.5, 40), P("downsample", 4, 1, 16), P("white_point", 1.0, 0.5, 2)]

    def apply(self, g, tex):
        v = self.v
        small = shrink(g, tex, down(tex, v["downsample"]))
        b = blur(g, g.run("bloom_isolate", size=small.size, tex=small, uGamma=v["gamma"]), v["sigma"])
        return g.run("bloom_comp", size=tex.size, tex=tex, uBloom=b, uAmount=v["amount"], uTint=v["tint"], uWhite=v["white_point"])


@effect
class Overlay(Effect):
    type = "overlay"
    params = [P("image", "lens_1", options=lambda: assets("overlays", ".png")), P("strength", 0.45), P("blend", "screen", options=BLENDS),
              P("drift", 0.3)]

    def apply(self, g, tex):
        return g.run("overlay", size=tex.size, tex=tex, uOver=g.image("overlays", self.v["image"]),
                     uStrength=self.v["strength"], uMode=BLENDS.index(self.v["blend"]), uDrift=self.v["drift"])


@effect
class Sharpen(Effect):
    type = "sharpen"
    params = [P("amount", 0.5, 0, 2)]

    def apply(self, g, tex):
        return g.run("sharpen", size=tex.size, tex=tex, uAmount=self.v["amount"])


@effect
class Noise(Effect):
    type = "noise"
    params = [P("amount", 0.2, 0, 0.5), P("size", 1.0, 1, 8), P("monochrome", False), P("blend", "overlay", options=["add", "overlay"]),
              P("shadow_amount", 0.0), P("animate", True)]

    def apply(self, g, tex):
        v = self.v
        return g.run("noise", size=tex.size, tex=tex, uAmount=v["amount"], uSize=v["size"], uMono=v["monochrome"],
                     uMode=["add", "overlay"].index(v["blend"]), uShadow=v["shadow_amount"], uAnimate=v["animate"])


@effect
class Grain(Effect):
    type = "grain"
    params = [P("texture", "fine", options=lambda: assets("grain", ".png")), P("amount", 0.35, 0, 0.5), P("scale", 1.0, 0.25, 4),
              P("shadow_amount", 0.5), P("animate", True)]

    def apply(self, g, tex):
        v = self.v
        return g.run("grain", size=tex.size, tex=tex, uGrain=g.image("grain", v["texture"], repeat=True), uAmount=v["amount"],
                     uScale=v["scale"], uShadow=v["shadow_amount"], uAnimate=v["animate"])


# Standard JPEG (ITU T.81 Annex K) quantization tables.
LUMA_Q = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
          18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
CHROMA_Q = [17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99] + [99] * 32


def quant_table(base, quality):
    """IJG quality scaling, same as libjpeg."""
    q = min(max(int(quality), 1), 100)
    s = 5000 // q if q < 50 else 200 - 2 * q
    return np.array([min(max((b * s + 50) // 100, 1), 255) for b in base], "f4")


def jpeg_size(w, h, long_side):
    k = min(1.0, long_side / max(w, h))
    return max(16, round(w * k / 16) * 16), max(16, round(h * k / 16) * 16)


@effect
class Jpeg(Temporal):
    """Real 8x8 DCT JPEG. Video mode adds codec behaviour: blocks that barely changed are skipped (they stick),
    and quality sags between keyframes, so the picture "breathes" like low-bitrate web video."""
    type = "jpeg"
    params = [P("quality", 60, 1, 100), P("long_side", 640, 40, 1920), P("pixelate", True), P("chroma_subsample", True),
              P("video", False), P("gop", 60, 1, 300), P("breathing", 0.5), P("skip_threshold", 0.03, 0, 0.2)]

    def encode(self, g, small, quality):
        y = g.run("jpeg_ycc", size=small.size, tex=small)
        c = g.run("copy", size=(small.width // 2, small.height // 2), tex=y) if self.v["chroma_subsample"] else y  # linear 2x2 = 4:2:0
        yi = g.run("jpeg_idct", size=y.size, tex=g.run("jpeg_dct", size=y.size, tex=y, uQ=quant_table(LUMA_Q, quality)))
        ci = g.run("jpeg_idct", size=c.size, tex=g.run("jpeg_dct", size=c.size, tex=c, uQ=quant_table(CHROMA_Q, quality)))
        return g.run("jpeg_rgb", size=small.size, tex=yi, uC=ci)

    def apply(self, g, tex):
        v = self.v
        small = shrink(g, tex, jpeg_size(*tex.size, v["long_side"]))
        if not v["video"]:
            return g.run("copy", size=tex.size, tex=self.encode(g, small, v["quality"]), uNearest=v["pixelate"])
        reset = self.textures(g, small, 2)
        phase = (self.n % v["gop"]) / v["gop"]
        rgb = self.encode(g, small, max(1, round(v["quality"] * (1 - v["breathing"] * phase))))
        out = g.run("jpeg_skip", out=self.hist[self.n % 2], tex=rgb, uSrc=small, uOld=self.hist[(self.n + 1) % 2],
                    uThreshold=v["skip_threshold"], uBlock=16.0, uKey=reset or self.n % v["gop"] == 0)
        self.n += 1
        return g.run("copy", size=tex.size, tex=out, uNearest=v["pixelate"])


@effect
class Vignette(Effect):
    type = "vignette"
    params = [P("strength", 1.0), P("size", 0.3), P("softness", 0.5), P("darken", 1.0), P("tint", [0.0, 0.0, 0.0], -0.5, 0.5)]

    def apply(self, g, tex):
        v = self.v
        return g.run("vignette", size=tex.size, tex=tex, uStrength=v["strength"], uSize=v["size"], uSoft=v["softness"],
                     uDarken=v["darken"], uTint=v["tint"])


@effect
class Clarity(Effect):
    type = "clarity"
    params = [P("amount", 0.2, -1, 2), P("radius", 8.0, 1, 30)]

    def apply(self, g, tex):
        b = g.run("copy", size=tex.size, tex=blur(g, shrink(g, tex, down(tex, 4)), self.v["radius"]))
        return g.run("clarity", size=tex.size, tex=tex, uBlur=b, uAmount=self.v["amount"])


@effect
class Bilateral(Effect):
    type = "bilateral"
    params = [P("sigma_space", 2.0, 0.5, 4), P("sigma_color", 0.1, 0.01, 0.5)]

    def apply(self, g, tex):
        return g.run("bilateral", size=tex.size, tex=tex, uSigmaS=self.v["sigma_space"], uSigmaL=self.v["sigma_color"])


@effect
class Desaturate(Effect):
    type = "desaturate"
    params = [P("amount", 1.0), P("mode", "luma", options=["luma", "hsv_value"])]

    def apply(self, g, tex):
        return g.run("desat", size=tex.size, tex=tex, uAmount=self.v["amount"], uMode=self.v["mode"] == "hsv_value")


@effect
class BlurPixelate(Effect):
    type = "blur_pixelate"
    params = [P("blur_type", "pixelate", options=["gaussian", "pixelate"]), P("sigma", 10.0, 0.1, 20), P("pixel_size", 8, 2, 64),
              P("mode", "uniform", options=["uniform", "vignette"]), P("vignette_size", 0.15, 0, 0.7), P("softness", 0.4, 0, 0.5),
              P("invert_mask", False)]

    def apply(self, g, tex):
        v = self.v
        if v["blur_type"] == "pixelate":
            b = g.run("pixelate", size=tex.size, tex=tex, uCell=float(v["pixel_size"]))
        else:
            b = blur(g, tex, v["sigma"])
        if v["mode"] == "uniform":
            return b
        return g.run("mask_mix", size=tex.size, tex=tex, uB=b, uSize=v["vignette_size"], uSoft=v["softness"], uInvert=v["invert_mask"])


# ---- extras (own versions of the mobile app's effects) ----


@effect
class BleachBypass(Effect):
    type = "bleach_bypass"
    params = [P("amount", 1.0), P("contrast", 0.15, -1, 1), P("saturation", -0.35, -1, 1)]

    def apply(self, g, tex):
        v = self.v
        return g.run("bleach", size=tex.size, tex=tex, uAmount=v["amount"], uContrast=v["contrast"], uSaturation=v["saturation"])


@effect
class Vhs(Effect):
    type = "vhs"
    params = [P("wobble", 1.0, 0, 5), P("chroma_shift", 4.0, -20, 20), P("chroma_blur", 3.0, 0, 10), P("tracking", 0.5),
              P("noise", 0.08, 0, 0.5), P("scanlines", 0.15), P("saturation", 1.1, 0, 2), P("softness", 1.5, 0, 4), P("ringing", 0.6, 0, 2),
              P("lines", 480, 120, 1080), P("dropouts", 0.4), P("jumps", 0.3), P("black_level", 0.03, 0, 0.2)]

    def apply(self, g, tex):
        v = self.v
        return g.run("vhs", size=tex.size, tex=tex, uWobble=v["wobble"], uChromaShift=v["chroma_shift"], uChromaBlur=v["chroma_blur"],
                     uTracking=v["tracking"], uNoise=v["noise"], uScan=v["scanlines"], uSaturation=v["saturation"],
                     uSoft=v["softness"], uRing=v["ringing"], uLines=float(v["lines"]), uDropouts=v["dropouts"], uJumps=v["jumps"],
                     uBlack=v["black_level"])


@effect
class Lcd(Temporal):
    type = "lcd"
    params = [P("cell", 6.0, 2, 24), P("gap", 0.15, 0, 0.8), P("subpixel", 0.8), P("brightness", 1.5, 0.5, 3), P("smear", 0.4, 0, 0.95),
              P("scan_bar", 0.4), P("moire", 0.3)]

    def apply(self, g, tex):
        v = self.v
        self.textures(g, tex, 2)
        lcd = g.run("lcd", size=tex.size, tex=tex, uCell=v["cell"], uGap=v["gap"], uSubpixel=v["subpixel"], uBright=v["brightness"],
                    uScanBar=v["scan_bar"], uMoire=v["moire"])
        self.n += 1
        return g.run("temporal_mix", out=self.hist[self.n % 2], tex=lcd, uPrev=self.hist[(self.n + 1) % 2], uAmount=v["smear"])


@effect
class Datamosh(Temporal):
    type = "datamosh"
    params = [P("mosh", True), P("block", 16, 4, 64), P("search", 8, 1, 24), P("residual", 0.1), P("iframe_every", 0, 0, 600)]

    def apply(self, g, tex):
        v = self.v
        reset = self.textures(g, tex, 3)  # hist = [prev input, held A, held B]
        prev, held_in, held_out = self.hist[0], self.hist[1 + (self.n + 1) % 2], self.hist[1 + self.n % 2]
        iframe = v["iframe_every"] and self.n % v["iframe_every"] == 0
        if reset or not v["mosh"] or iframe:
            out = g.run("copy", out=held_out, tex=tex)
        else:
            bs = v["block"]
            mv = g.run("mosh_motion", size=(math.ceil(tex.width / bs), math.ceil(tex.height / bs)), tex=tex, uPrev=prev,
                       uBlock=float(bs), uSearch=v["search"])
            out = g.run("mosh", out=held_out, tex=tex, uHeld=held_in, uPrev=prev, uMotion=mv, uBlock=float(bs), uResidual=v["residual"])
        g.run("copy", out=prev, tex=tex)
        self.n += 1
        return out


@effect
class Lightburst(Effect):
    type = "lightburst"
    params = [P("threshold", 0.75), P("rays", 6, 2, 12), P("length", 0.25, 0.02, 1), P("decay", 3.0, 0, 8), P("strength", 1.2, 0, 4),
              P("rotation", 0.0, 0, 360), P("spin", 0.0, -2, 2), P("twinkle", 0.5), P("spectral", 0.3), P("tint", [1.0, 1.0, 1.0], color=True)]

    def apply(self, g, tex):
        v = self.v
        small = shrink(g, tex, down(tex, 4))
        b = blur(g, g.run("bright", size=small.size, tex=small, uThreshold=v["threshold"]), 1.5)
        s = g.run("streaks", size=small.size, tex=b, uRays=v["rays"], uLength=v["length"], uDecay=v["decay"], uTwinkle=v["twinkle"],
                  uSpectral=v["spectral"], uAngle=math.radians(v["rotation"]) + g.time * v["spin"])
        return g.run("bloom_comp", size=tex.size, tex=tex, uBloom=s, uAmount=v["strength"], uTint=v["tint"], uWhite=1.0)


@effect
class ChromaticAberration(Effect):
    type = "chromatic_aberration"
    params = [P("amount", 2.0, 0, 20), P("radial", True)]

    def apply(self, g, tex):
        return g.run("chroma", size=tex.size, tex=tex, uAmount=self.v["amount"], uRadial=self.v["radial"])


@effect
class TextStamp(Effect):
    type = "text_stamp"
    params = [P("text", "'%y %m %d"), P("style", "digicam", options=["digicam", "film_led", "vcr_osd", "camcorder_osd", "cctv_osd", "vcr", "dotmatrix", "clean"]),
              P("font", "DejaVu Sans Bold", options=text.font_names), P("align", "right", options=["left", "center", "right"]),
              P("x", 0.93), P("y", 0.9), P("size", 1.5, 0.3, 6), P("tracking", 0.0, -0.3, 1.0),
              P("color", [1.0, 0.45, 0.08], color=True), P("glow", 0.7), P("hot_core", 0.5), P("shadow", 0.0),
              P("slant", 0.12, -0.5, 0.5), P("blink", 0.0, 0, 4), P("opacity", 0.9)]
    key = tex_ = t0 = None

    def format(self, g):
        """strftime codes, plus {tc} (H:MM:SS since the step started) and {tcf} (HH:MM:SS:FF at 30 fps)."""
        if self.t0 is None:
            self.t0 = g.time
        e = max(0.0, g.time - self.t0)
        s = int(e)
        return (time.strftime(self.v["text"], time.localtime(g.wall)).replace("{tc}", f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}")
                .replace("{tcf}", f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{int(e * 30) % 30:02d}"))

    def apply(self, g, tex):
        v = self.v
        lines = self.format(g).split("|")  # "|" starts a new line
        key = (lines, str(v), tex.height)
        if key != self.key:
            img, self.pad = text.render(tex.height, lines, v["style"], v["font"], v["size"], v["color"], v["glow"], v["hot_core"],
                                        v["shadow"], v["slant"], v["tracking"], v["align"])
            h, w = img.shape[:2]
            if self.tex_ is None or self.tex_.size != (w, h):
                self.tex_ = g.ctx.texture((w, h), 4)
                self.tex_.repeat_x = self.tex_.repeat_y = False
            self.tex_.write(img[::-1].tobytes())
            self.key = key
        w, h = self.tex_.size
        x0, y0 = text.place(*tex.size, w, h, self.pad, v["x"], v["y"], v["align"])
        visible = v["blink"] <= 0 or (g.time * v["blink"]) % 1 < 0.5
        return g.run("stamp", size=tex.size, tex=tex, uStamp=self.tex_, uOpacity=v["opacity"] * visible,
                     uRect=(x0 / tex.width, 1 - (y0 + h) / tex.height, w / tex.width, h / tex.height))


@effect
class CcdSmear(Effect):
    type = "ccd_smear"
    params = [P("threshold", 0.92), P("strength", 0.6, 0, 3), P("falloff", 2.0, 0, 20), P("tint", [0.85, 0.8, 1.0], color=True)]

    def apply(self, g, tex):
        v = self.v
        small = shrink(g, tex, down(tex, 2))
        b = g.run("bright", size=small.size, tex=small, uThreshold=v["threshold"])
        s = g.run("smear", size=small.size, tex=b, uFalloff=v["falloff"])
        return g.run("bloom_comp", size=tex.size, tex=tex, uBloom=s, uAmount=v["strength"], uTint=v["tint"], uWhite=1.0)


@effect
class Flash(Effect):
    type = "flash"
    params = [P("strength", 0.6, 0, 1.5), P("falloff", 3.0, 0.5, 12), P("x", 0.5), P("y", 0.55), P("cool", 0.5), P("flicker", 0.1)]

    def apply(self, g, tex):
        v = self.v
        s = v["strength"] * (1 + v["flicker"] * (rng.random() - 0.5) * 0.4)  # cheap flash/video light never fires the same twice
        return g.run("flash", size=tex.size, tex=tex, uStrength=s, uFalloff=v["falloff"], uCenter=(v["x"], 1 - v["y"]), uCool=v["cool"])


@effect
class BitDepth(Effect):
    type = "bit_depth"
    params = [P("levels", 24, 2, 64), P("dither", "none", options=["none", "noise", "bayer"]), P("dither_amount", 1.0)]

    def apply(self, g, tex):
        v = self.v
        return g.run("bitdepth", size=tex.size, tex=tex, uLevels=float(v["levels"]),
                     uDither=["none", "noise", "bayer"].index(v["dither"]), uAmount=v["dither_amount"])


# ---- camera behaviour over time ----


@effect
class CameraLife(Effect):
    """Auto exposure + auto white balance that lag behind the scene, and slow exposure hunting, like a cheap camera."""
    type = "camera_life"
    params = [P("auto_exposure", 0.8), P("target", 0.4, 0.1, 0.8), P("max_boost", 2.0, 0, 4), P("white_balance", 0.4),
              P("speed", 0.5, 0.05, 3), P("hunting", 0.15)]
    state = last = None

    def apply(self, g, tex):
        v = self.v
        first = self.state is None or self.last is None or g.time < self.last
        if self.state is None:
            self.state, self.n = [g.texture(1, 1) for _ in range(2)], 0
        avg = g.run("average", size=(1, 1), tex=shrink(g, tex, (64, 36)))  # centre-weighted metering
        keep = 0.0 if first else math.exp(-(g.time - self.last) / v["speed"])
        self.last = g.time
        self.n += 1
        adapted = g.run("temporal_mix", out=self.state[self.n % 2], tex=avg, uPrev=self.state[(self.n + 1) % 2], uAmount=keep)
        return g.run("expose", size=tex.size, tex=tex, uAvg=adapted, uTarget=v["target"], uAE=v["auto_exposure"], uMaxEv=v["max_boost"],
                     uAWB=v["white_balance"], uHunt=v["hunting"])


@effect
class SensorNoise(Effect):
    """Physically shaped sensor noise: shot noise, blotchy chroma noise in the shadows, row banding, fixed hot pixels."""
    type = "sensor_noise"
    params = [P("luma", 0.06, 0, 0.4), P("chroma", 0.1, 0, 0.5), P("chroma_size", 6.0, 1, 24), P("shadows", 0.7), P("banding", 0.0),
              P("hot_pixels", 0.0)]

    def apply(self, g, tex):
        v = self.v
        return g.run("sensor", size=tex.size, tex=tex, uLuma=v["luma"], uChroma=v["chroma"], uChromaSize=v["chroma_size"],
                     uShadows=v["shadows"], uBanding=v["banding"], uHot=v["hot_pixels"])


@effect
class LensFlare(Effect):
    """Ghosts and a halo mirrored through the lens centre from every bright spot, so the flare follows the lights."""
    type = "lens_flare"
    params = [P("threshold", 0.85), P("strength", 0.6, 0, 3), P("ghosts", 5, 1, 10), P("dispersal", 0.35, 0.05, 1), P("halo", 0.5, 0, 2),
              P("halo_width", 0.45, 0.1, 0.9), P("chroma", 0.012, 0, 0.05), P("rainbow", 0.6), P("tint", [1.0, 0.95, 0.9], color=True)]

    def apply(self, g, tex):
        v = self.v
        small = shrink(g, tex, down(tex, 4))
        b = blur(g, g.run("bright", size=small.size, tex=small, uThreshold=v["threshold"]), 1.0)
        f = g.run("flare", size=small.size, tex=b, uGhosts=v["ghosts"], uDispersal=v["dispersal"], uHalo=v["halo"],
                  uHaloWidth=v["halo_width"], uChroma=v["chroma"], uRainbow=v["rainbow"])
        return g.run("bloom_comp", size=tex.size, tex=tex, uBloom=blur(g, f, 2.0), uAmount=v["strength"], uTint=v["tint"], uWhite=1.0)


@effect
class LightLeak(Effect):
    type = "light_leak"
    params = [P("strength", 0.4, 0, 1.5), P("speed", 0.15, 0, 1), P("scale", 1.5, 0.3, 5), P("edge", 0.6),
              P("color_a", [1.0, 0.45, 0.1], color=True), P("color_b", [1.0, 0.15, 0.3], color=True)]

    def apply(self, g, tex):
        v = self.v
        return g.run("leak", size=tex.size, tex=tex, uStrength=v["strength"], uSpeed=v["speed"], uScale=v["scale"], uEdge=v["edge"],
                     uColorA=v["color_a"], uColorB=v["color_b"])


@effect
class Interlace(Temporal):
    """Alternate lines come from the previous frame, so motion combs like interlaced video."""
    type = "interlace"
    params = [P("amount", 1.0), P("line_height", 1.5, 1, 4)]

    def apply(self, g, tex):
        v = self.v
        self.textures(g, tex, 1)
        out = g.run("interlace", size=tex.size, tex=tex, uPrev=self.hist[0], uAmount=v["amount"], uLine=v["line_height"], uField=self.n % 2)
        g.run("copy", out=self.hist[0], tex=tex)
        self.n += 1
        return out


@effect
class FrameRate(Temporal):
    """Hold frames to a lower frame rate (phone video, webcams, GIFs), with optional uneven pacing."""
    type = "frame_rate"
    params = [P("fps", 15.0, 1, 60), P("jitter", 0.0)]
    next_t = 0.0

    def apply(self, g, tex):
        v = self.v
        reset = self.textures(g, tex, 1)
        if reset or g.time >= self.next_t or g.time < self.next_t - 2:
            g.run("copy", out=self.hist[0], tex=tex)
            self.next_t = g.time + (1 + v["jitter"] * (rng.random() * 1.5 - 0.5)) / v["fps"]
        return self.hist[0]


# ---- hardware-signal effects: everything below works at the format's own resolution, not the output's ----

NTSC, PAL = dict(size=(760, 480), line_us=52.6, head=8), dict(size=(936, 576), line_us=52.0, head=9)
# Format: luma and chroma bandwidth (MHz), noise and timing relative to VHS SP. Starting points from the format specs;
# the shape of the response is calibrated in tools/compare_reference.py against real captures of colour bars.
TAPE_FORMATS = {
    "VHS SP": dict(luma=2.5, chroma=0.34, noise=1.0, timing=1.0, ring=1.0),
    "VHS LP": dict(luma=2.1, chroma=0.31, noise=1.35, timing=1.3, ring=1.15),
    "VHS EP": dict(luma=1.7, chroma=0.27, noise=1.8, timing=1.7, ring=1.3),
    "S-VHS": dict(luma=4.2, chroma=0.34, noise=0.7, timing=1.0, ring=0.7),
    "Betamax": dict(luma=2.8, chroma=0.42, noise=0.85, timing=0.9, ring=0.8),
    "Video8": dict(luma=2.4, chroma=0.34, noise=0.9, timing=0.8, ring=1.2),
    "Hi8": dict(luma=4.2, chroma=0.34, noise=0.65, timing=0.8, ring=0.8),
}


def mhz_sigma(mhz, width, line_us):
    """Gaussian sigma in samples for a lowpass with this -3 dB bandwidth."""
    cycles_per_line = mhz * line_us
    return 0.1325 / cycles_per_line * width


@effect
class Tape(Temporal):
    """A tape signal chain: encode, comb, record, replay, decode. Each dub repeats record and replay."""
    type = "tape"
    params = [P("format", "VHS SP", options=list(TAPE_FORMATS)), P("standard", "NTSC", options=["NTSC", "PAL"]),
              P("input", "Composite", options=["Composite", "Direct (camcorder)"]), P("generation", 1, 1, 6), P("noise", 1.0, 0, 4), P("tracking", 0.0),
              P("dropouts", 0.25), P("jitter", 1.0, 0, 4), P("ringing", 1.0, 0, 3), P("head_switch", 1.0), P("saturation", 0.76, 0, 1.6),
              P("black_level", 0.03, 0, 0.2), P("interlace", 1.0), P("overscan", False)]

    def apply(self, g, tex):
        v, f = self.v, TAPE_FORMATS[self.v["format"]]
        std = PAL if v["standard"] == "PAL" else NTSC
        size, width = std["size"], std["size"][0]
        pal, composite = int(v["standard"] == "PAL"), int(v["input"] == "Composite")
        small = g.run("copy", size=size, tex=shrink(g, tex, size))
        self.textures(g, small, 1)
        field = g.frame & 1
        x = g.run("tape_encode", size=size, tex=small, uPrev=self.hist[0], uInterlace=v["interlace"], uPal=pal, uComposite=composite, uField=field)
        x = g.run("tape_sep", size=size, tex=x, uPal=pal, uComposite=composite, uField=field)
        for gen in range(v["generation"]):
            loss = 1 + 0.18 * gen  # each dub loses a little more bandwidth and adds its own noise
            x = g.run("tape_record", size=size, tex=x, uLumaSigma=mhz_sigma(f["luma"], width, std["line_us"]) * loss,
                      uChromaSigma=mhz_sigma(f["chroma"], width, std["line_us"]) * loss, uChromaDelay=width * 0.0035 * loss,
                      uRing=0.75 * f["ring"] * v["ringing"], uRingWidth=width * 0.0032, uSmear=0.3, uChromaBlend=0.5, uSat=v["saturation"] ** (1 / v["generation"]))
            x = g.run("tape_play", size=size, tex=x, uSeed=(g.frame * 0.618034 + gen * 0.31) % 1 * 97.0, uNoise=0.056 * f["noise"] * v["noise"],
                      uChromaNoise=0.05 * f["noise"] * v["noise"], uStreak=2.0, uJitter=0.55 * f["timing"] * v["jitter"], uWave=1.1 * f["timing"] * v["jitter"],
                      uFlag=2.4 * v["jitter"], uDropouts=v["dropouts"] * f["noise"], uTracking=v["tracking"], uHeadSwitch=v["head_switch"] if gen == 0 else 0.0,
                      uHeadGain=0.012, uHeadLines=std["head"], uChromaLoss=0.0006 * f["noise"])
        g.run("copy", out=self.hist[0], tex=small)
        return g.run("tape_out", size=tex.size, tex=x, uBlack=v["black_level"], uWhite=0.9, uKnee=0.8, uOverscan=0.07 if v["overscan"] else 0.0, uBlank=0.012)


def seed(g):
    """Noise seed for a frame: repeatable, because the frame number drives it."""
    return (g.frame * 0.618034) % 1


@effect
class CamcorderSensor(Temporal):
    """The camera end of a camcorder: one small CCD, slow AGC, autofocus and a hand holding it."""
    type = "camcorder_sensor"
    params = [P("sensor_noise", 1.0, 0, 4), P("agc", 1.0, 0, 2), P("highlight_knee", 0.68, 0.4, 0.95), P("false_color", 1.0, 0, 3), P("softness", 1.5, 0, 8),
              P("autofocus_hunt", 0.25), P("white_balance_drift", 0.4), P("handheld", 0.6, 0, 3), P("low_light_color_loss", 0.7), P("dark_hunting", 0.5, 0, 2)]
    focus = 0.0

    def apply(self, g, tex):
        v = self.v
        small = shrink(g, tex, (16, 9))
        if self.textures(g, small, 1):
            g.run("copy", out=self.hist[0], tex=small)
        avg = g.run("temporal_mix", size=small.size, tex=small, uPrev=self.hist[0], uAmount=0.93)  # AGC reacts over about a second
        g.run("copy", out=self.hist[0], tex=avg)
        t = g.time
        h = v["handheld"]
        # Layered sines stand in for a hand: slow drift, a small tremor, and breathing.
        offset = (h * 0.0035 * (math.sin(t * 0.9) + 0.6 * math.sin(t * 2.3 + 1.1) + 0.2 * math.sin(t * 7.1)),
                  h * 0.0040 * (math.sin(t * 0.7 + 2.0) + 0.5 * math.sin(t * 2.9) + 0.2 * math.sin(t * 8.3 + 0.5)))
        roll = h * 0.0022 * (math.sin(t * 0.53) + 0.5 * math.sin(t * 1.7 + 1.0))
        # Contrast autofocus: every few seconds it wanders off and back.
        phase = (t * 0.17) % 1
        hunt = v["autofocus_hunt"] * 7 * math.sin(min(phase / 0.09, 1) * math.pi) ** 2 if phase < 0.09 else 0.0
        drift = v["white_balance_drift"] * 0.05
        wb = (1 + drift * math.sin(t * 0.21), 1.0, 1 - drift * math.sin(t * 0.21 + 0.4))
        return g.run("camcorder_sensor", size=tex.size, tex=tex, uAvg=avg, uOffset=offset, uRoll=roll, uZoom=1 + 0.02 * min(h, 1.5), uFocus=v["softness"] + hunt,
                     uKnee=v["highlight_knee"], uGain=v["agc"], uNoise=0.012 * v["sensor_noise"], uMoire=0.35 * v["false_color"],
                     uShadowChroma=v["low_light_color_loss"], uSeed=seed(g), uWB=wb, uHunt=v["dark_hunting"] * (0.6 * math.sin(t * 2.7) + 0.4 * math.sin(t * 6.1)))


NIGHT_TINTS = {"Green (NightShot)": [0.42, 1.0, 0.5], "Green phosphor": [0.2, 1.0, 0.25], "Mono": [1.0, 1.0, 1.0], "Cool mono": [0.82, 0.92, 1.0]}


@effect
class NightVision(Temporal):
    """Old infrared video: no colour, a pool of LED light, slow exposure and a lot of gain."""
    type = "night_vision"
    params = [P("tint", "Green (NightShot)", options=list(NIGHT_TINTS)), P("gain", 1.0, 0.2, 3), P("ir_spot_size", 0.42, 0.1, 2), P("ambient", 0.05),
              P("spot_x", 0.5), P("spot_y", 0.5), P("reflectance", 0.5, 0, 2), P("noise", 0.1, 0, 0.5), P("ghosting", 0.55, 0, 0.95), P("bloom", 0.45, 0, 2),
              P("hum_bars", 0.0), P("hot_pixels", 0.3), P("resolution", 420, 120, 1080), P("phosphor_white", 0.2), P("target_exposure", 0.2, 0.05, 0.6)]
    state = None

    def apply(self, g, tex):
        v = self.v
        raw = g.run("ir_response", size=tex.size, tex=tex, uCenterX=v["spot_x"], uCenterY=v["spot_y"], uSpot=v["ir_spot_size"], uRange=v["ambient"], uReflect=v["reflectance"])
        avg = g.run("average", size=(1, 1), tex=shrink(g, raw, (64, 36)))
        if self.state is None:
            self.state, self.n = [g.texture(1, 1) for _ in range(2)], 0
            g.run("copy", out=self.state[1], tex=avg)
        self.n += 1
        level = g.run("temporal_mix", out=self.state[self.n % 2], tex=avg, uPrev=self.state[(self.n + 1) % 2], uAmount=0.9)
        ir = g.run("ir_gain", size=tex.size, tex=raw, uAvg=level, uTarget=v["target_exposure"])
        h = min(v["resolution"], tex.height)
        size = (max(2, tex.width * h // tex.height), h)
        lowres = g.run("copy", size=size, tex=shrink(g, ir, size))
        reset = self.textures(g, lowres, 1)
        if reset:
            g.run("copy", out=self.hist[0], tex=lowres)
        glow = blur(g, shrink(g, g.run("bright", size=lowres.size, tex=lowres, uThreshold=0.55), down(lowres, 4)), 4.0)
        out = g.run("night_vision", size=tex.size, tex=lowres, uTrail=self.hist[0], uGlow=glow, uGhost=v["ghosting"], uBloom=v["bloom"], uNoise=v["noise"], uGain=v["gain"],
                    uHum=v["hum_bars"], uHumSpeed=0.11, uHot=v["hot_pixels"], uSeed=seed(g), uPhosphor=v["phosphor_white"], uTint=NIGHT_TINTS[v["tint"]])
        trail = g.run("temporal_mix", size=lowres.size, tex=lowres, uPrev=self.hist[0], uAmount=v["ghosting"] * 0.8)
        g.run("copy", out=self.hist[0], tex=trail)
        return out


@effect
class Crt(Temporal):
    """Point a camera at an old TV: mask, scanlines, glow and curved glass. Use after tape, as the last step."""
    type = "crt"
    params = [P("curvature", 0.7, 0, 2), P("mask", 0.3), P("scanlines", 0.55), P("glow", 0.25, 0, 1), P("lines", 480, 240, 1080), P("flicker", 0.6), P("persistence", 0.25),
              P("corner", 0.1, 0, 0.5)]

    def apply(self, g, tex):
        v = self.v
        if self.textures(g, tex, 1):
            g.run("copy", out=self.hist[0], tex=tex)
        glow = blur(g, shrink(g, tex, down(tex, 4)), 5.0)
        out = g.run("crt", size=tex.size, tex=tex, uGlow=glow, uPersist=self.hist[0], uCurve=v["curvature"], uMask=v["mask"], uScan=v["scanlines"], uBloom=v["glow"],
                    uLines=float(v["lines"]), uFlicker=v["flicker"], uPersistence=v["persistence"], uCorner=v["corner"])
        g.run("copy", out=self.hist[0], tex=out)
        return out


@effect
class FilmDamage(Effect):
    """A worn print running through a projector: gate weave, flicker, dust and scratches. Pairs with grain."""
    type = "film_damage"
    params = [P("weave", 0.5, 0, 3), P("flicker", 0.4), P("dust", 0.35), P("scratches", 0.3)]

    def apply(self, g, tex):
        v = self.v
        t = g.frame * 0.618034
        wx = (math.sin(t * 23.1) + 0.5 * math.sin(t * 7.7)) * 0.0009 * v["weave"]
        wy = (math.sin(t * 19.3 + 1.2) + 0.5 * math.sin(t * 5.1)) * 0.0014 * v["weave"]
        return g.run("film_damage", size=tex.size, tex=tex, uWeaveX=wx, uWeaveY=wy, uFlicker=v["flicker"] * 0.05 * math.sin(t * 37.7), uDust=v["dust"], uScratches=v["scratches"],
                     uSeed=seed(g) * 50)


# Built-in styles: named parameter sets per effect (applied on top of the defaults). Users add more from the UI.
WHITE, ORANGE, RED = [1.0, 1.0, 1.0], [1.0, 0.45, 0.08], [1.0, 0.2, 0.15]
STYLES = {
    "color_grade": {"Warm 2000s": dict(temperature=0.35, saturation=0.15, contrast=0.1, lift=[0.03, 0.01, 0.0]),
                    "Cold digital": dict(temperature=-0.4, tint=-0.1, contrast=0.2, saturation=-0.1),
                    "Faded": dict(contrast=-0.25, lift=[0.08, 0.08, 0.1], saturation=-0.25),
                    "Punchy": dict(contrast=0.35, saturation=0.35, exposure=0.1)},
    "lut": {"Subtle": dict(intensity=0.5), "Full": dict(intensity=1.0)},
    "gaussian_blur": {"Soft": dict(sigma=0.8), "Dreamy": dict(sigma=3.0, downsample=2), "Out of focus": dict(sigma=8.0, downsample=4)},
    "bloom": {"Soft glow": dict(amount=0.5, gamma=2.0, sigma=6.0), "CCD violet": dict(amount=1.0, tint=[0.25, 0.0, 1.0], gamma=3.5, sigma=3.0, downsample=6),
              "Laptop blue": dict(amount=1.0, tint=[0.0, 0.0, 1.0], gamma=3.0), "Warm haze": dict(amount=0.8, tint=[1.0, 0.6, 0.25], gamma=1.8, sigma=10.0),
              "Blown out": dict(amount=1.8, gamma=1.5, sigma=12.0, downsample=8)},
    "overlay": {"Faint flare": dict(strength=0.25), "Strong flare": dict(strength=0.8), "Ghosts": dict(image="lens_4", strength=0.6),
                "Still": dict(drift=0.0)},
    "sharpen": {"Light": dict(amount=0.25), "Crunchy": dict(amount=1.0), "Re-upload halos": dict(amount=1.6)},
    "noise": {"Fine": dict(amount=0.08, monochrome=True, blend="overlay"), "Low light": dict(amount=0.25, shadow_amount=1.0, size=2.0),
              "Color speckle": dict(amount=0.3, size=2.0, blend="add"), "TV static": dict(amount=0.5, monochrome=True, blend="add")},
    "grain": {"Fine film": dict(texture="fine", amount=0.15), "Coarse film": dict(texture="coarse", amount=0.3, scale=1.5)},
    "jpeg": {"High": dict(quality=90, long_side=1080, pixelate=False), "Medium": dict(quality=60, long_side=640),
             "Low": dict(quality=25, long_side=480), "Potato": dict(quality=8, long_side=240),
             "Web video 2008": dict(quality=35, long_side=640, pixelate=False, video=True, gop=90, breathing=0.6, skip_threshold=0.04),
             "Webcam stream": dict(quality=70, long_side=640, pixelate=False, video=True, gop=45, breathing=0.3)},
    "vignette": {"Subtle": dict(strength=0.4, size=0.4, softness=0.6), "Heavy": dict(strength=1.0, size=0.15, softness=0.5),
                 "Green phone": dict(strength=0.6, size=0.3, darken=0.2, tint=[-0.1, 0.0, -0.1]),
                 "Pink edges": dict(strength=0.8, size=0.25, darken=0.0, tint=[0.15, -0.02, 0.08])},
    "clarity": {"Soft skin": dict(amount=-0.5), "Punchy": dict(amount=0.6)},
    "bilateral": {"Smooth": dict(sigma_space=2.0, sigma_color=0.08), "Plastic": dict(sigma_space=4.0, sigma_color=0.2)},
    "desaturate": {"Half": dict(amount=0.5), "Full": dict(amount=1.0), "Bright mono": dict(amount=1.0, mode="hsv_value")},
    "blur_pixelate": {"Censor": dict(blur_type="pixelate", pixel_size=24), "8-bit": dict(blur_type="pixelate", pixel_size=6),
                      "Soft edges": dict(blur_type="gaussian", sigma=8.0, mode="vignette", vignette_size=0.25)},
    "bleach_bypass": {"Light": dict(amount=0.5, contrast=0.05, saturation=-0.15), "Classic": dict(),
                      "Heavy": dict(amount=1.0, contrast=0.35, saturation=-0.6)},
    "vhs": {"Clean tape": dict(wobble=0.4, tracking=0.0, noise=0.03, chroma_shift=2.0, ringing=0.3, dropouts=0.1, jumps=0.0),
            "Worn tape": dict(), "Destroyed tape": dict(wobble=3.0, tracking=1.0, noise=0.2, chroma_shift=10.0, chroma_blur=6.0, softness=3.0,
                                                        dropouts=1.0, jumps=1.0, lines=240),
            "Camcorder 8mm": dict(wobble=0.6, tracking=0.1, noise=0.05, chroma_shift=3.0, lines=400, dropouts=0.2, jumps=0.1)},
    "tape": {"Clean SP": dict(), "Worn LP": dict(format="VHS LP", noise=1.3, dropouts=0.5, tracking=0.15), "Bad EP": dict(format="VHS EP", noise=1.5, dropouts=0.8, tracking=0.5),
             "3rd generation": dict(generation=3), "Camcorder Video8": dict(format="Video8", input="Direct (camcorder)"),
             "Camcorder Hi8": dict(format="Hi8", input="Direct (camcorder)"), "S-VHS": dict(format="S-VHS"), "Betamax": dict(format="Betamax"),
             "PAL SP": dict(standard="PAL")},
    "camcorder_sensor": {"Bright day": dict(sensor_noise=0.6, agc=0.3), "Indoors": dict(), "Dark room": dict(agc=1.6, sensor_noise=2.0), "On a tripod": dict(handheld=0.0)},
    "night_vision": {"NightShot": dict(), "Green tube": dict(tint="Green phosphor", ghosting=0.7, noise=0.16, phosphor_white=0.5), "Mono CCTV": dict(tint="Mono", ghosting=0.3, hum_bars=0.5),
                     "Bright IR": dict(ambient=0.6, gain=1.6, noise=0.05)},
    "crt": {"Living room TV": dict(), "Security monitor": dict(curvature=0.4, mask=0.2, scanlines=0.8), "Big curve": dict(curvature=1.6, corner=0.25)},
    "film_damage": {"Clean print": dict(weave=0.3, dust=0.1, scratches=0.0), "Used print": dict(), "Beat up": dict(weave=1.5, flicker=0.9, dust=0.9, scratches=0.9)},
    "lcd": {"Phone screen": dict(cell=4.0, gap=0.1, subpixel=0.5, smear=0.2, scan_bar=0.2, moire=0.15), "Old monitor": dict(),
            "Stadium screen": dict(cell=14.0, gap=0.35, subpixel=1.0, brightness=2.0, smear=0.1, scan_bar=0.6, moire=0.0)},
    "datamosh": {"Light smear": dict(residual=0.4, iframe_every=90), "Heavy smear": dict(residual=0.05), "Melt": dict(residual=0.0, block=32, search=16)},
    "lightburst": {"Star": dict(rays=6), "Anamorphic": dict(rays=2, length=0.6, tint=[0.4, 0.6, 1.0], decay=1.5, twinkle=0.2),
                   "Spinning": dict(rays=8, spin=0.6), "Diffraction": dict(rays=6, spectral=0.9, twinkle=0.7)},
    "chromatic_aberration": {"Subtle": dict(amount=1.5), "Cheap lens": dict(amount=4.0), "Broken": dict(amount=12.0, radial=False)},
    "text_stamp": {
        "Digicam date": dict(),
        "Film date back": dict(text="'%y %m %d", style="film_led", color=[1.0, 0.3, 0.05], glow=0.9, hot_core=0.8, slant=0.08, size=1.3),
        "VCR play": dict(text="PLAY ▶", style="vcr_osd", align="left", x=0.07, y=0.1, size=1.6, color=WHITE, glow=0.0, hot_core=0.0,
                         shadow=0.9, slant=0.0),
        "Camcorder REC": dict(text="● REC", style="camcorder_osd", align="left", x=0.07, y=0.1, size=1.6, color=RED, glow=0.0, hot_core=0.0,
                              shadow=0.9, slant=0.0, blink=1.0),
        "Camcorder date": dict(text="%b %d %Y|%I:%M:%S %p", style="camcorder_osd", align="right", x=0.93, y=0.86, size=1.3, color=WHITE, glow=0.0,
                               hot_core=0.0, shadow=0.9, slant=0.0),
        "CCTV title": dict(text="CAM 03  %m-%d-%Y  %H:%M:%S", style="cctv_osd", align="left", x=0.05, y=0.92, size=1.15, color=WHITE, glow=0.0, hot_core=0.0,
                           shadow=0.9, slant=0.0),
        "Viewfinder timecode": dict(text="{tcf}", style="camcorder_osd", align="right", x=0.93, y=0.1, size=1.4, color=WHITE, glow=0.15,
                                    hot_core=0.0, shadow=0.6, slant=0.0),
        "Clean caption": dict(text="%B %d, %Y", style="clean", align="center", x=0.5, y=0.9, size=1.4, color=WHITE, glow=0.0,
                              hot_core=0.0, shadow=0.8, slant=0.0)},
    "ccd_smear": {"Subtle": dict(strength=0.4), "Strong": dict(strength=1.5, threshold=0.85, falloff=0.0)},
    "flash": {"Point & shoot": dict(), "Harsh night": dict(strength=1.1, falloff=5.0, cool=0.8, flicker=0.2)},
    "bit_depth": {"Banding": dict(levels=24), "GIF": dict(levels=6, dither="bayer"), "Posterized": dict(levels=4),
                  "Noisy dither": dict(levels=8, dither="noise")},
    "camera_life": {"Digicam": dict(auto_exposure=0.8, white_balance=0.4, speed=0.6, hunting=0.1),
                    "Cheap webcam": dict(auto_exposure=1.0, white_balance=0.7, speed=0.25, hunting=0.35),
                    "Camcorder": dict(auto_exposure=0.9, white_balance=0.5, speed=0.4, hunting=0.15),
                    "Brighten dark room": dict(auto_exposure=1.0, target=0.45, max_boost=3.0, speed=0.8, hunting=0.0)},
    "sensor_noise": {"Clean": dict(luma=0.02, chroma=0.02), "Low light": dict(luma=0.1, chroma=0.2, chroma_size=8.0),
                     "Phone 2006": dict(luma=0.12, chroma=0.25, chroma_size=4.0, banding=0.4),
                     "Webcam": dict(luma=0.1, chroma=0.15, banding=0.3, shadows=0.9),
                     "Dying sensor": dict(luma=0.15, chroma=0.3, banding=1.0, hot_pixels=1.0)},
    "lens_flare": {"Subtle": dict(strength=0.3), "Cheap zoom": dict(strength=0.8, ghosts=7, dispersal=0.3, chroma=0.02),
                   "Rainbow": dict(strength=0.7, rainbow=1.0, halo=1.0)},
    "light_leak": {"Warm": dict(), "Cool": dict(color_a=[0.6, 0.8, 1.0], color_b=[0.9, 0.95, 1.0], strength=0.3),
                   "Magenta": dict(color_a=[1.0, 0.2, 0.6], color_b=[0.6, 0.2, 1.0]),
                   "Burn": dict(strength=1.0, speed=0.3, edge=0.3, color_a=[1.0, 0.35, 0.0], color_b=[1.0, 0.85, 0.4])},
    "interlace": {"Combing": dict(), "Subtle": dict(amount=0.5)},
    "frame_rate": {"Film 24": dict(fps=24.0), "Webcam 15": dict(fps=15.0, jitter=0.4), "GIF 10": dict(fps=10.0),
                   "Slideshow 4": dict(fps=4.0, jitter=0.3)},
}
for _t, _s in STYLES.items():
    REGISTRY[_t].styles = _s
