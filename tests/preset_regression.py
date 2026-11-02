"""Pixel regression for saved presets: same seed, frames and clock must give identical renders.

Run from the project root:
  python -m tests.preset_regression record DIR OUT.json    write hashes for every preset .json in DIR
  python -m tests.preset_regression check DIR OUT.json     compare against them
"""
import hashlib
import json
import random
import sys
from pathlib import Path

import cv2
import moderngl
import numpy as np

from badcamera import effects, presets
from badcamera.gpu import GPU

W, H, FRAMES = 640, 360, 40


def frame(i):
    """Colour ramps, text and a moving highlight, so temporal steps see real change. BGR like a camera."""
    y, x = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W, 3), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = x * 255 // W, y * 255 // H, 128
    cv2.circle(img, (100 + i * 8, 120), 30, (255, 255, 255), -1)
    cv2.putText(img, "BadCamera", (40, 250), cv2.FONT_HERSHEY_DUPLEX, 2, (20, 200, 255), 3)
    return img


def seed():
    random.seed(1234)
    if hasattr(effects, "rng"):
        effects.rng.seed(1234)


def render(g, cam, path):
    p = json.loads(path.read_text(encoding="utf-8"))
    steps = presets.build(p)
    seed()
    h = hashlib.sha256()
    for i in range(FRAMES):
        cam.write(frame(i).tobytes())
        g.begin_frame(i / 60)
        src = g.run("ingest", size=(W, H), tex=cam)
        out = presets.process(g, steps, src)
        errors = [e.error for e in steps if e.error]
        assert not errors, (path.name, errors)
        h.update(g.read(out).tobytes())
    return h.hexdigest()


def main():
    mode, folder, ref = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    ctx = moderngl.create_standalone_context(backend="egl")
    g = GPU(ctx)
    cam = ctx.texture((W, H), 3, alignment=1)
    got = {f.name: render(g, cam, f) for f in sorted(folder.glob("*.json")) if f.name not in ("styles.json", "transform.json")}
    if mode == "record":
        ref.write_text(json.dumps(got, indent=1))
        print("recorded", list(got))
        return
    want = json.loads(ref.read_text())
    bad = [k for k in want if got.get(k) != want[k]]
    print("identical:", [k for k in want if k not in bad])
    assert not bad, f"changed: {bad}"


if __name__ == "__main__":
    main()
