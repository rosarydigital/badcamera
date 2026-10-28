"""Generate BadCamera's own LUTs (.cube), lens-reflection overlays and grain textures into assets/."""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "assets"
N = 33

# Each look is a small grade recipe: lift/gain/gamma per channel, saturation, contrast (S-curve), fade, split toning, mono.
LOOKS = {
    "ccd":             dict(lift=(0.02, 0.0, 0.05), gain=(1.0, 0.97, 1.08), sat=1.2, contrast=0.25, split=((0.0, 0.0, 0.04), (0.04, 0.0, 0.03))),
    "nokia":           dict(lift=(0.03, 0.05, 0.0), gain=(0.95, 1.05, 0.85), sat=0.85, contrast=0.35, fade=0.05),
    "iphone3":         dict(gain=(1.06, 1.0, 0.9), gamma=(0.95, 1.0, 1.05), sat=1.15, contrast=0.2),
    "laptop":          dict(lift=(0.0, 0.03, 0.08), gain=(0.88, 0.97, 1.1), sat=0.75, fade=0.08),
    "coloredvignette": dict(lift=(0.03, 0.0, 0.04), sat=1.1, contrast=0.15, split=((0.03, 0.0, 0.05), (0.04, 0.03, 0.0))),
    "nashville":       dict(lift=(0.12, 0.05, 0.08), gain=(1.02, 0.95, 0.85), sat=0.9, contrast=-0.1, split=((0.06, 0.0, 0.04), (0.05, 0.03, 0.0))),
    "chief_keef":      dict(gain=(1.1, 0.95, 0.85), sat=1.4, contrast=0.4, split=((0.05, 0.0, 0.0), (0.06, 0.03, 0.0))),
    "nuke":            dict(gain=(1.15, 1.05, 0.7), sat=1.8, contrast=0.6),
    "phreshboy":       dict(lift=(0.0, 0.03, 0.06), gain=(0.95, 1.05, 1.1), sat=1.25, contrast=0.3),
    "sepia":           dict(mono=True, split=((0.1, 0.05, -0.02), (0.12, 0.06, -0.04)), contrast=0.1, fade=0.05),
    "2014":            dict(lift=(0.05, 0.05, 0.08), sat=0.8, contrast=0.15, fade=0.12, split=((0.0, 0.02, 0.05), (0.05, 0.03, 0.0))),
    "money":           dict(gain=(0.9, 1.1, 0.85), sat=1.3, contrast=0.35, split=((0.0, 0.04, 0.0), (0.04, 0.05, 0.0))),
    "pandora":         dict(lift=(0.03, 0.0, 0.08), gain=(0.95, 0.9, 1.1), sat=1.1, split=((0.03, 0.0, 0.08), (0.06, 0.0, 0.05))),
    "bleach_bypass":   dict(sat=0.45, contrast=0.55, gain=(1.0, 1.0, 1.02)),
    "stressor":        dict(sat=0.6, contrast=0.8, lift=(0.0, 0.02, 0.03), gamma=(1.1, 1.05, 1.0)),
    "bw":              dict(mono=True, contrast=0.3),
    "bw_clamped":      dict(mono=True, contrast=0.7, fade=0.1),
    "pale_blue":       dict(lift=(0.04, 0.08, 0.14), gain=(0.9, 0.98, 1.08), sat=0.65, contrast=-0.05, fade=0.1),
    "galaxy":          dict(lift=(0.04, 0.0, 0.1), gain=(1.0, 0.85, 1.15), sat=1.3, contrast=0.35, split=((0.04, 0.0, 0.1), (0.06, 0.0, 0.08))),
    "desolate":        dict(lift=(0.0, 0.02, 0.04), gain=(0.9, 0.95, 1.0), sat=0.35, contrast=0.45, gamma=(1.1, 1.1, 1.05)),
    "roadkill":        dict(lift=(0.05, 0.08, 0.0), gain=(0.97, 1.06, 0.72), gamma=(1.0, 0.95, 1.15), sat=0.85, contrast=0.4,
                             split=((0.0, 0.03, -0.02), (0.03, 0.05, -0.04))),
    "ashtray":         dict(lift=(0.06, 0.04, 0.02), gain=(1.0, 0.92, 0.78), sat=0.6, contrast=0.2, fade=0.1, split=((0.04, 0.02, 0.0), (0.05, 0.03, 0.0))),
}


def grade(rgb, lift=(0, 0, 0), gain=(1, 1, 1), gamma=(1, 1, 1), sat=1.0, contrast=0.0, fade=0.0, split=((0, 0, 0), (0, 0, 0)), mono=False):
    luma = rgb @ np.array([0.299, 0.587, 0.114])
    if mono:
        rgb = np.repeat(luma[:, None], 3, 1)
    c = rgb * np.array(gain) + np.array(lift) * (1 - rgb)
    c = np.clip(c, 0, 1) ** np.array(gamma)
    c = c + contrast * (c - 0.5) * (1 - np.abs(2 * c - 1))  # S-curve around mid grey, keeps 0 and 1
    l = (c @ np.array([0.299, 0.587, 0.114]))[:, None]
    c = l + (c - l) * sat
    c = c + np.array(split[0]) * (1 - l) + np.array(split[1]) * l
    c = fade * 0.15 + c * (1 - fade * 0.25)
    return np.clip(c, 0, 1)


def write_cube(path, n, data):
    with open(path, "w") as f:
        f.write(f"TITLE \"{path.stem}\"\nLUT_3D_SIZE {n}\n")
        f.writelines(f"{r:.6f} {g:.6f} {b:.6f}\n" for r, g, b in data)


def identity(n):
    i = np.linspace(0, 1, n)
    b, g, r = np.meshgrid(i, i, i, indexing="ij")  # red varies fastest, as .cube requires
    return np.stack([r, g, b], -1).reshape(-1, 3)


def lens_reflection(seed, size=512):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size] / size
    img = np.zeros((size, size, 3))
    sx, sy = rng.uniform(0.15, 0.4), rng.uniform(0.1, 0.35)  # light source; ghosts mirror through centre
    for _ in range(rng.integers(4, 9)):
        t = rng.uniform(-0.6, 1.6)
        cx, cy = sx + (1 - 2 * sx) * t, sy + (1 - 2 * sy) * t
        r = rng.uniform(0.02, 0.12)
        d = np.hypot(x - cx, y - cy) / r
        ring = rng.random() < 0.3
        shape = np.exp(-((d - 1) ** 2) * 30) if ring else np.clip(1 - d, 0, 1) ** rng.uniform(0.3, 1.5)
        img += shape[..., None] * rng.uniform(0.2, 1, 3) * rng.uniform(0.15, 0.5)
    img += (np.exp(-np.hypot(x - sx, y - sy) * 9) * 0.6)[..., None] * np.array([1, 0.9, 0.8])
    return np.clip(img * 255, 0, 255).astype(np.uint8)


def icon(size=1024):
    """Flat square app icon: blue tile, white camera, orange date-stamp dot. Drawn large and downsampled for smooth edges."""
    from PIL import Image, ImageDraw
    s = size / 64
    img = Image.new("RGBA", (size, size), (59, 89, 152, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, size - 3 * s, size, size], fill=(41, 72, 125, 255))  # darker bottom edge, like the top bar
    d.rectangle([10 * s, 20 * s, 54 * s, 48 * s], fill=(255, 255, 255, 255))  # body
    d.rectangle([22 * s, 15 * s, 36 * s, 20 * s], fill=(255, 255, 255, 255))  # viewfinder hump
    d.rectangle([44 * s, 23 * s, 50 * s, 27 * s], fill=(255, 140, 26, 255))  # flash / date LED
    for r, col, dx, dy in ((11, (59, 89, 152), 0, 0), (8.5, (255, 255, 255), 0, 0), (6.5, (29, 33, 41), 0, 0), (2, (216, 223, 234), 0, -1.8)):
        cx, cy = (31 + dx) * s, (34 + dy) * s  # lens rings, then a small glint
        d.ellipse([cx - r * s, cy - r * s, cx + r * s, cy + r * s], fill=col + (255,))
    return img


def main():
    for sub in ("luts", "overlays", "grain"):
        (ASSETS / sub).mkdir(parents=True, exist_ok=True)
    ident = identity(N)
    write_cube(ASSETS / "luts" / "identity.cube", N, ident)
    for name, look in LOOKS.items():
        write_cube(ASSETS / "luts" / f"{name}.cube", N, grade(ident, **look))
    for i in range(1, 11):
        cv2.imwrite(str(ASSETS / "overlays" / f"lens_{i}.png"), lens_reflection(i)[..., ::-1])
    rng = np.random.default_rng(0)
    for name, sigma in (("fine", 0.6), ("coarse", 1.5)):
        n = cv2.GaussianBlur(np.tile(rng.normal(0, 1, (256, 256)), (3, 3)), (0, 0), sigma)[256:512, 256:512]  # tile so it wraps seamlessly
        n = (n - n.mean()) / n.std() * 0.18 + 0.5
        cv2.imwrite(str(ASSETS / "grain" / f"{name}.png"), np.clip(n * 255, 0, 255).astype(np.uint8))
    big = icon()
    big.resize((256, 256), Image.Resampling.LANCZOS).save(ASSETS / "icon.png")
    big.resize((256, 256), Image.Resampling.LANCZOS).save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"assets written to {ASSETS}")


if __name__ == "__main__":
    main()
