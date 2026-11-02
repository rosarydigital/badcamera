"""Render through the real OpenFX plugin with a small host, and check it matches the app's own chain frame for frame.

Run from the project root, after building: python -m tests.test_plugin HOST PLUGIN
"""
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import moderngl
import numpy as np

from badcamera import effects, presets, serve
from badcamera.effects import make
from badcamera.gpu import GPU

W, H = 640, 360


def frame():
    y, x = np.mgrid[0:H, 0:W]
    img = np.ones((H, W, 4), "f4")
    img[..., 0], img[..., 1], img[..., 2] = x / W, y / H, 0.4
    cv2.circle(img, (450, 120), 40, (1.0, 1.0, 1.0, 1.0), -1)
    return img


def direct(steps_fn, img, frames):
    ctx = moderngl.create_standalone_context(backend="egl")
    g = GPU(ctx)
    tex = ctx.texture((W, H), 4, img.tobytes(), dtype="f4")
    steps = steps_fn()
    for f in range(frames):
        g.begin_frame(f / 30)
        g.frame = f
        effects.rng.seed(f)
        out = presets.process(g, steps, g.run("copy", size=(W, H), tex=tex))
    return np.frombuffer(g.fbo(out).read(components=4, dtype="f4", alignment=1), "f4").reshape(H, W, 4)


def main():
    host, plugin = sys.argv[1], sys.argv[2]
    listing = subprocess.run([host, plugin, "list"], capture_output=True, text=True).stdout.strip().splitlines()
    n = len(effects.REGISTRY)
    assert len(listing) == n + 1, len(listing)
    print(f"host sees {len(listing)} plugins")
    img = frame()
    tmp = Path(tempfile.mkdtemp())
    (tmp / "in.bin").write_bytes(img.tobytes())
    engine = subprocess.Popen([sys.executable, "-c", "from badcamera import serve; serve.serve()"])
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", serve.PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    def through(pid, *args):
        r = subprocess.run([host, plugin, "render", pid, str(tmp / "in.bin"), str(tmp / "out.bin"), str(W), str(H), *args], capture_output=True, text=True, timeout=60)
        assert "rendered" in r.stdout, (pid, r.stdout, r.stderr)
        return np.fromfile(tmp / "out.bin", "f4").reshape(H, W, 4)

    try:
        bad = []
        for t in sorted(effects.REGISTRY):  # every effect, through the real plugin
            a = through(f"com.rosarydigital.badcamera.{t}", "frames=3")
            b = direct(lambda: [make(t)], img, 3)
            d = np.abs(a[..., :3] - b[..., :3]).mean()
            print(f"{t:22} difference {d:.5f}", flush=True)
            if d > 0.02:
                bad.append(t)
        assert not bad, bad
        a = through("com.rosarydigital.badcamera.tape", "bc_mix=0.0")
        assert np.abs(a[..., :3] - img[..., :3]).max() < 1e-5, "Mix at 0 must pass the picture through"
        assert np.abs(a[..., 3] - 1).max() < 1e-6
        a = through("com.rosarydigital.badcamera.tape", "format=VHS EP", "noise=0.0")
        b = direct(lambda: [make("tape", {"format": "VHS EP", "noise": 0.0})], img, 1)
        assert np.abs(a[..., :3] - b[..., :3]).mean() < 0.01, "controls must reach the engine"
        a = through("com.rosarydigital.badcamera.look", "bc_look=Night Vision Security", "frames=3")
        b = direct(lambda: presets.build(next(p for p in presets.load_all() if p["name"] == "Night Vision Security")), img, 3)
        d = np.abs(a[..., :3] - b[..., :3]).mean()
        print(f"look preset difference {d:.5f}")
        assert d < 0.02
    finally:
        s = socket.create_connection(("127.0.0.1", serve.PORT))
        h = json.dumps({"quit": True}).encode()
        s.sendall(len(h).to_bytes(4, "little") + h)
        engine.wait(5)
    # With no engine at all, the plugin must pass the picture through rather than fail the render.
    import os
    env = {**os.environ, "BADCAMERA_ENGINE": "/nonexistent"}
    t0 = time.time()
    r = subprocess.run([host, plugin, "render", "com.rosarydigital.badcamera.tape", str(tmp / "in.bin"), str(tmp / "out.bin"), str(W), str(H)], capture_output=True, text=True, timeout=60, env=env)
    a = np.fromfile(tmp / "out.bin", "f4").reshape(H, W, 4)
    assert "rendered" in r.stdout and np.abs(a - img).max() < 1e-5, r.stdout
    print(f"no engine: picture passes through after {time.time() - t0:.0f} s")
    print("all plugin checks passed")


if __name__ == "__main__":
    main()
