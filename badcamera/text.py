"""Text rendering for stamps: 7-segment digicam date, 5x7 dot-matrix VCR/camcorder OSD, and clean TrueType."""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .gpu import ROOT

SYSTEM_FONTS = {
    "DejaVu Sans Bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVu Sans Mono Bold": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "Liberation Sans Bold": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "Noto Sans Mono Bold": "/usr/share/fonts/truetype/noto/NotoSansMono-Bold.ttf",
    "FreeMono Bold": "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",
    "Ubuntu Sans": "/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf",
    "Verdana Bold": "C:/Windows/Fonts/verdanab.ttf",
    "Tahoma Bold": "C:/Windows/Fonts/tahomabd.ttf",
    "Arial Bold": "C:/Windows/Fonts/arialbd.ttf",
    "Consolas Bold": "C:/Windows/Fonts/consolab.ttf",
    "Courier New Bold": "C:/Windows/Fonts/courbd.ttf",
}


def fonts():
    """Installed system fonts plus any .ttf/.otf dropped into assets/fonts/."""
    out = {k: v for k, v in SYSTEM_FONTS.items() if Path(v).exists()}
    for p in sorted((ROOT / "assets" / "fonts").glob("*.[ot]tf")):
        out[p.stem] = str(p)
    return out


def font_names():
    return list(fonts())


def load_font(name, px):
    path = fonts().get(name) or next(iter(fonts().values()), None)
    return ImageFont.truetype(path, max(6, int(px))) if path else ImageFont.load_default()


# ---- 5x7 dot-matrix font (the classic character-generator shapes used by VCR / camcorder on-screen displays) ----
# Each glyph: 7 rows, 5 bits per row, MSB = leftmost dot.
PIXEL_FONT = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E), "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F), "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02), "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E), "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E), "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    "A": (0x0E, 0x11, 0x11, 0x11, 0x1F, 0x11, 0x11), "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E), "D": (0x1C, 0x12, 0x11, 0x11, 0x11, 0x12, 0x1C),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F), "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F), "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E), "J": (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11), "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11), "N": (0x11, 0x11, 0x19, 0x15, 0x13, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E), "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D), "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E), "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E), "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A), "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x11, 0x0A, 0x04, 0x04, 0x04), "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00), ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    ",": (0x00, 0x00, 0x00, 0x00, 0x0C, 0x04, 0x08), "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    "/": (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x00), "'": (0x0C, 0x04, 0x08, 0x00, 0x00, 0x00, 0x00),
    "!": (0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04), "?": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04),
    "+": (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00), "=": (0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02), ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    "<": (0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02), ">": (0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08),
    "%": (0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03), "#": (0x0A, 0x0A, 0x1F, 0x0A, 0x1F, 0x0A, 0x0A),
    "*": (0x00, 0x04, 0x15, 0x0E, 0x15, 0x04, 0x00), "_": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),
    "|": (0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "▶": (0x10, 0x18, 0x1C, 0x1E, 0x1C, 0x18, 0x10), "◀": (0x01, 0x03, 0x07, 0x0F, 0x07, 0x03, 0x01),
    "●": (0x00, 0x0E, 0x1F, 0x1F, 0x1F, 0x0E, 0x00), "■": (0x00, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x00),
    "Ⅱ": (0x1B, 0x1B, 0x1B, 0x1B, 0x1B, 0x1B, 0x1B),  # pause
}


def dot_matrix(text, h, round_dots=False, tracking=0.0):
    """5x7 glyphs scaled to whole pixels: square dots (VCR OSD) or round dots (camcorder viewfinder LCD)."""
    k = max(1, round(h / 7))
    gap = max(1, round(1 + tracking * 5))
    rows = np.zeros((7, max(1, len(text) * (5 + gap))), np.float32)
    for i, ch in enumerate(text):
        glyph = PIXEL_FONT.get(ch) or PIXEL_FONT.get(ch.upper()) or PIXEL_FONT["?"]
        for r, bits in enumerate(glyph):
            for c in range(5):
                if bits >> (4 - c) & 1:
                    rows[r, i * (5 + gap) + c] = 1
    if round_dots:
        y, x = np.mgrid[0:k, 0:k] + 0.5
        dot = (np.hypot(x - k / 2, y - k / 2) <= k * 0.42).astype(np.float32)
    else:
        dot = np.ones((k, k), np.float32)
    return np.kron(rows, dot)


# ---- 7-segment LCD (film-camera / early digicam date stamp) ----
SEGMENTS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg",
            "9": "abcdfg", "-": "g", "A": "abcefg", "b": "cdefg", "C": "adef", "c": "deg", "d": "bcdeg", "E": "adefg", "F": "aefg",
            "H": "bcefg", "h": "cefg", "J": "bcde", "L": "def", "n": "ceg", "o": "cdeg", "P": "abefg", "r": "eg", "S": "afgcd",
            "t": "defg", "U": "bcdef", "u": "cde", "y": "bcdfg"}


def seven_segment(text, h, tracking=0.0):
    """Draw text as 7-segment LCD glyphs, 3x supersampled; returns a float mask."""
    ss = 3
    H = h * ss
    W, T = 0.52 * H, 0.14 * H
    g = T * 0.18
    extra = tracking * W
    adv = {" ": W * 0.75, ":": T * 2.6, "'": T * 2.2, ".": T * 2.2}
    fallback = load_font("DejaVu Sans Mono Bold", H * 1.3)  # letters a 7-segment display can't show (M, W, X...)

    def segs_for(ch):
        return SEGMENTS.get(ch, SEGMENTS.get(ch.upper(), SEGMENTS.get(ch.lower())))

    def advance(ch):
        if ch in adv:
            return adv[ch] + extra
        return (W + T * 1.3 if segs_for(ch) is not None else fallback.getlength(ch) + T * 0.6) + extra

    width = int(sum(advance(c) for c in text) + T) + 1
    img = Image.new("L", (max(1, width), int(H + T)), 0)
    d = ImageDraw.Draw(img)

    def horiz(x0, x1, y):
        d.polygon([(x0, y), (x0 + T / 2, y - T / 2), (x1 - T / 2, y - T / 2), (x1, y), (x1 - T / 2, y + T / 2), (x0 + T / 2, y + T / 2)], 255)

    def vert(x, y0, y1):
        d.polygon([(x, y0), (x + T / 2, y0 + T / 2), (x + T / 2, y1 - T / 2), (x, y1), (x - T / 2, y1 - T / 2), (x - T / 2, y0 + T / 2)], 255)

    x = T / 2
    for ch in text:
        if ch in adv:
            if ch == ":":
                d.rectangle([x + T * 0.6, H * 0.3, x + T * 1.6, H * 0.3 + T], 255)
                d.rectangle([x + T * 0.6, H * 0.65, x + T * 1.6, H * 0.65 + T], 255)
            elif ch == "'":
                d.polygon([(x + T * 0.7, 0), (x + T * 1.7, 0), (x + T * 1.2, H * 0.34), (x + T * 0.5, H * 0.34)], 255)
            elif ch == ".":
                d.rectangle([x + T * 0.5, H - T, x + T * 1.5, H], 255)
            x += advance(ch)
            continue
        segs = segs_for(ch)
        if segs is None:
            d.text((x, H), ch, font=fallback, fill=255, anchor="ls")
            x += advance(ch)
            continue
        left, right, top, mid, bot = x + T / 2, x + W - T / 2, T / 2, H / 2, H - T / 2
        for s in segs:
            {"a": lambda: horiz(left + g, right - g, top), "g": lambda: horiz(left + g, right - g, mid),
             "d": lambda: horiz(left + g, right - g, bot), "f": lambda: vert(left, top + g, mid - g),
             "b": lambda: vert(right, top + g, mid - g), "e": lambda: vert(left, mid + g, bot - g),
             "c": lambda: vert(right, mid + g, bot - g)}[s]()
        x += advance(ch)
    img = img.resize((max(1, img.width // ss), max(1, img.height // ss)), Image.Resampling.LANCZOS)
    return np.asarray(img, np.float32) / 255


def truetype(text, h, font_name, tracking=0.0):
    """Anti-aliased TrueType, drawn glyph by glyph so letter spacing can be adjusted."""
    font = load_font(font_name, h * 1.35)  # ~cap height h
    extra = tracking * h * 0.5
    asc, desc = font.getmetrics()
    width = int(sum(font.getlength(c) + extra for c in text) + h) + 2
    img = Image.new("L", (max(1, width), asc + desc + 4), 0)
    d = ImageDraw.Draw(img)
    x = 2.0
    for c in text:
        d.text((x, 2), c, font=font, fill=255)
        x += font.getlength(c) + extra
    m = np.asarray(img, np.float32) / 255
    cols = np.nonzero(m.max(0) > 0)[0]
    return m[:, : cols[-1] + 3] if len(cols) else m[:, :2]


def block(lines, style, h, font_name, slant, tracking, align):
    """Stack rendered lines with the given alignment and shear for italic."""
    render_line = {"digicam": lambda s: seven_segment(s, h, tracking), "vcr": lambda s: dot_matrix(s, h, False, tracking),
                   "dotmatrix": lambda s: dot_matrix(s, h, True, tracking)}.get(style, lambda s: truetype(s, h, font_name, tracking))
    masks = [render_line(s) for s in lines]
    gap = int(h * (0.6 if style in ("vcr", "dotmatrix") else 0.45))
    rows = sum(m.shape[0] for m in masks) + gap * (len(masks) - 1)
    inner = max(m.shape[1] for m in masks)
    W = inner + int(abs(slant) * rows) + 2  # room for the shear
    out = np.zeros((rows, W), np.float32)
    y = 0
    for m in masks:
        x = {"left": 0, "center": (inner - m.shape[1]) // 2, "right": inner - m.shape[1]}[align]
        out[y:y + m.shape[0], x:x + m.shape[1]] = m
        y += m.shape[0] + gap
    if slant:
        M = np.float32([[1, -slant, slant * rows if slant > 0 else 0], [0, 1, 0]])
        out = cv2.warpAffine(out, M, (W, rows), flags=cv2.INTER_LINEAR)
    return out


def compose(mask, color, glow, hot_core, shadow, style, h):
    """Layer shadow/outline (black), glow (colour), text (colour) and a white-hot core into straight-alpha RGBA."""
    pad = int(h * 0.7) + 4
    m = np.pad(mask, pad)
    color = np.array(color, np.float32)
    layers = []
    if shadow > 0:
        if style in ("vcr", "dotmatrix"):  # hard black outline + drop shadow, like a character-generator OSD
            k = max(1, round(h / 7))
            sh = cv2.dilate(m, np.ones((2 * k + 1, 2 * k + 1), np.uint8))
            sh = np.maximum(sh, np.roll(sh, (k, k), (0, 1)))
        else:
            off = max(1, int(h * 0.07))
            sh = cv2.GaussianBlur(np.roll(cv2.dilate(m, None), (off, off), (0, 1)), (0, 0), max(1.0, h * 0.06))
        layers.append((np.zeros(3, np.float32), np.clip(sh * shadow, 0, 1)))
    if glow > 0:
        wide = cv2.GaussianBlur(m, (0, 0), max(2.0, h * 0.35))
        tight = cv2.GaussianBlur(m, (0, 0), max(1.0, h * 0.08))
        layers.append((color, np.clip((wide * 1.4 + tight * 0.8) * glow, 0, 1)))
    layers.append((color, m))
    if hot_core > 0:  # LED/film-burn stamps are hotter (whiter) in the middle of each stroke
        core = np.clip(cv2.GaussianBlur(cv2.erode(m, None), (0, 0), max(0.6, h * 0.03)) * 1.4 - 0.4, 0, 1) * m
        layers.append((np.clip(color * 0.35 + 0.75, 0, 1), core * hot_core))
    a = np.zeros(m.shape, np.float32)
    rgb = np.zeros(m.shape + (3,), np.float32)  # premultiplied
    for col, la in layers:
        rgb = col * la[..., None] + rgb * (1 - la[..., None])
        a = la + a * (1 - la)
    rgba = np.zeros(m.shape + (4,), np.float32)
    rgba[..., :3] = rgb / np.maximum(a, 1e-4)[..., None]
    rgba[..., 3] = a
    return rgba, pad


def render(frame_h, lines, style, font_name, size, color, glow, hot_core, shadow, slant, tracking, align):
    """Text block as RGBA uint8 (rows top-first), plus the padding around the glyphs."""
    px = size * frame_h / 720 * 22
    rgba, pad = compose(block(lines, style, px, font_name, slant, tracking, align), color, glow, hot_core, shadow, style, px)
    return np.clip(rgba * 255, 0, 255).astype(np.uint8), pad


def place(frame_w, frame_h, block_w, block_h, pad, x, y, align):
    """Top-left pixel of the block so its text edge (per alignment) sits at (x, y) as frame fractions."""
    ax = {"left": pad, "center": block_w / 2, "right": block_w - pad}[align]
    return int(x * frame_w - ax), int(y * frame_h - block_h / 2)
