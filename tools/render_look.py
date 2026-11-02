"""Render a preset JSON or a still through an effect chain and write frames to a video, for comparison with real footage.

  python tools/render_look.py IMAGE OUT.png '{"type": "tape", "params": {}}' [more steps...]
  python tools/render_look.py IMAGE OUT.mkv --preset "VHS"   (24 frames, near-lossless)
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import moderngl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from badcamera import presets  # noqa: E402
from badcamera.gpu import GPU  # noqa: E402


def main():
    img = cv2.imread(sys.argv[1])
    h, w = img.shape[:2]
    if w % 2 or h % 2:
        img = img[:h & ~1, :w & ~1]
        h, w = img.shape[:2]
    out = sys.argv[2]
    if sys.argv[3] == "--preset":
        p = next(x for x in presets.load_all() if x["name"] == sys.argv[4])
    else:
        p = {"steps": [json.loads(a) for a in sys.argv[3:]]}
    steps = presets.build(p)
    ctx = moderngl.create_standalone_context(backend="egl")
    g = GPU(ctx)
    cam = ctx.texture((w, h), 3, img.tobytes(), alignment=1)
    frames = []
    for i in range(30):
        g.begin_frame(i / 30)
        o = presets.process(g, steps, g.run("ingest", size=(w, h), tex=cam))
        err = [e.error for e in steps if e.error]
        assert not err, err
        if i >= 6:
            frames.append(g.read(o))
    if out.endswith(".png"):
        cv2.imwrite(out, frames[-1][..., ::-1])
        return
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "30", "-i", "-",
                          "-c:v", "ffv1", out], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.tobytes())
    p.stdin.close()
    p.wait()


if __name__ == "__main__":
    main()
