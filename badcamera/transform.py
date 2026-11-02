"""Rotate / stretch / squash / move a source frame, before any effects run, like moving the camera itself."""
import json
import math

import numpy as np

from .presets import USER

PATH = USER / "transform.json"
DEFAULT = {"rotate": 0.0, "stretch": 1.0, "squash": 1.0, "move_x": 0.0, "move_y": 0.0, "zoom": 1.0, "flip_h": False, "flip_v": False}


def new(values=None):
    return {**DEFAULT, **(values or {})}


def is_identity(t):
    return all(t.get(k, v) == v for k, v in DEFAULT.items())


def load():
    try:
        return new(json.loads(PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return new()


def save(t):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(t, indent=1), encoding="utf-8")


def matrix(t, out, src, mirror=False):
    """3x3 column-major (output uv -> source uv) for ingest.glsl. Fits src inside out, so clips of any size letterbox."""
    ow, oh, sw, sh = out[0], out[1], src[0], src[1]
    a = math.radians(t["rotate"])
    c, s = math.cos(a), math.sin(a)
    sx = t["zoom"] * t["stretch"] * (-1 if t["flip_h"] != mirror else 1)
    sy = t["zoom"] * t["squash"] * (-1 if t["flip_v"] else 1)
    fit = min(ow / sw, oh / sh)

    def m(*row):
        return np.array(row, float).reshape(3, 3)

    to_px = m(ow, 0, -ow / 2, 0, oh, -oh / 2, 0, 0, 1)  # output uv -> pixels around the centre
    unmove = m(1, 0, -t["move_x"] * ow, 0, 1, -t["move_y"] * oh, 0, 0, 1)
    unrotate = m(c, -s, 0, s, c, 0, 0, 0, 1)
    unscale = m(1 / sx, 0, 0, 0, 1 / sy, 0, 0, 0, 1)
    to_src = m(1 / (fit * sw), 0, 0.5, 0, 1 / (fit * sh), 0.5, 0, 0, 1)
    return (to_src @ unscale @ unrotate @ unmove @ to_px).T.flatten()  # GLSL mat3 is column-major
