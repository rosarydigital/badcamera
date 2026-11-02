"""Headless self-check: run every preset on a synthetic frame and compare GPU JPEG with libjpeg.

Run: ~/.local/share/badcamera/venv/bin/python -m tests.test_core   (from the project root)
Writes one PNG per preset to captures/test/ for a visual look.
"""
import json

import cv2
import moderngl
import numpy as np

from badcamera import presets, text
from badcamera.effects import REGISTRY, jpeg_size, make, quant_table, LUMA_Q
from badcamera.gpu import GPU, ROOT, read_cube

W, H = 640, 360


def test_frame():
    y, x = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W, 3), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = x * 255 // W, y * 255 // H, 128
    cv2.circle(img, (450, 120), 30, (255, 255, 255), -1)  # highlight for bloom / lightburst
    cv2.putText(img, "BadCamera", (40, 250), cv2.FONT_HERSHEY_DUPLEX, 2, (20, 200, 255), 3)
    return img  # BGR, like a camera frame


def test_cpu():
    (ROOT / "captures" / "test").mkdir(parents=True, exist_ok=True)
    assert list(quant_table(LUMA_Q, 50)) == LUMA_Q
    assert quant_table(LUMA_Q, 100).max() == 1
    assert jpeg_size(1280, 720, 500) == (496, 288)
    n, data = read_cube(ROOT / "assets" / "luts" / "identity.cube")
    assert np.allclose(data[1], [1 / (n - 1), 0, 0], atol=1e-5)  # red varies fastest
    for t, cls in REGISTRY.items():
        for name, st in cls.styles.items():
            assert set(st) <= {q.key for q in cls.params}, (t, name, set(st) - {q.key for q in cls.params})
    for style in ("digicam", "film_led", "vcr_osd", "camcorder_osd", "cctv_osd", "vcr", "dotmatrix", "clean"):
        img, pad = text.render(720, ["'26 10 28", "PLAY ▶ 12:48 PM"], style, "DejaVu Sans Bold", 1.5, [1, 0.5, 0.1], 0.6, 0.5, 0.8,
                               0.1 if style == "digicam" else 0.0, 0.0, "left")
        assert img.ndim == 3 and img.shape[2] == 4 and img[..., 3].max() == 255 and pad > 0, style
        cv2.imwrite(str(ROOT / "captures" / "test" / f"text_{style}.png"), cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA))
    assert text.place(1000, 500, 200, 50, 10, 0.9, 0.5, "right") == (900 - 190, 225)
    for p in presets.load_all():
        for s in p["steps"]:
            keys = {q.key for q in REGISTRY[s["type"]].params}
            assert set(s["params"]) <= keys, (p["name"], s["type"], set(s["params"]) - keys)


def test_gpu():
    ctx = moderngl.create_standalone_context(backend="egl")
    g = GPU(ctx)
    frame = test_frame()
    cam = ctx.texture((W, H), 3, frame.tobytes(), alignment=1)
    out_dir = ROOT / "captures" / "test"
    out_dir.mkdir(parents=True, exist_ok=True)

    for p in presets.load_all():
        steps = presets.build(p)
        for t in range(4):  # several frames so temporal steps run their non-reset path
            g.begin_frame(t / 60)
            out = presets.process(g, steps, g.run("ingest", size=(W, H), tex=cam))
        errors = [f"{e.type}: {e.error}" for e in steps if e.error]
        assert not errors, (p["name"], errors)
        rgb = g.read(out)
        assert rgb.shape == (H, W, 3) and rgb.std() > 1, p["name"]
        cv2.imwrite(str(out_dir / f"{p['name'].replace('/', '_').replace(' ', '_')}.png"), rgb[..., ::-1])

    # Every effect at defaults and in every built-in style must run.
    for t, cls in REGISTRY.items():
        for params in [{}] + list(cls.styles.values()):
            e = make(t, params)
            for f in range(3):
                g.begin_frame(f / 60)
                presets.process(g, [e], g.run("ingest", size=(W, H), tex=cam))
            assert not e.error, (t, params, e.error)

    # Nothing static: with a frozen input frame, every look must still change over time.
    for p in presets.load_all():
        if p["name"] in ("Blur/Pixelate", "Clean (grade only)"):  # utility presets, deliberately still
            continue
        steps = presets.build(p)
        shots = []
        for f in range(150):  # 2.5 s at 60 fps so slow effects (frame holds, AE, leaks) get going
            g.begin_frame(f / 60)
            out = presets.process(g, steps, g.run("ingest", size=(W, H), tex=cam))
            if f in (120, 149):
                shots.append(g.read(out).astype(float))
        motion = np.abs(shots[0] - shots[1]).mean()
        assert motion > 0.5, f"{p['name']} is static (mean change {motion:.2f})"

    # GPU JPEG should lose about as much detail as libjpeg at the same quality.
    g.begin_frame(0)
    src = g.run("ingest", size=(W, H), tex=cam)
    ref_in = g.read(src)
    gpu = g.read(make("jpeg", {"quality": 20, "long_side": W, "pixelate": False}).apply(g, src)).astype(float)
    ok, enc = cv2.imencode(".jpg", ref_in[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 20])
    lib = cv2.imdecode(enc, cv2.IMREAD_COLOR)[..., ::-1].astype(float)
    d_gpu, d_lib = np.abs(gpu - ref_in).mean(), np.abs(lib - ref_in).mean()
    print(f"jpeg q20 error vs original: gpu {d_gpu:.2f}, libjpeg {d_lib:.2f}")
    assert 0.5 < d_gpu / d_lib < 2, "GPU JPEG error is far from libjpeg's"

    # Timing at camera resolution for the heaviest presets.
    import time
    cam720 = ctx.texture((1280, 720), 3, cv2.resize(frame, (1280, 720)).tobytes(), alignment=1)
    for p in presets.load_all():
        steps = presets.build(p)
        ctx.finish()
        t0 = time.perf_counter()
        for i in range(30):
            g.begin_frame(i / 60)
            out = presets.process(g, steps, g.run("ingest", size=(1280, 720), tex=cam720))
        ctx.finish()
        print(f"{p['name']:<20} {(time.perf_counter() - t0) / 30 * 1000:6.2f} ms/frame @720p")


if __name__ == "__main__":
    test_cpu()
    test_gpu()
    print("all checks passed; preset renders in", ROOT / "captures" / "test")
