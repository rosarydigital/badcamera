"""Headless engine for the Resolve plugin. The plugin sends frames here and gets them back through the same effect chain as the app,
so a look matches in both and every effect works without a second implementation."""
import json
import socket
import struct
import sys
from pathlib import Path

import moderngl
import numpy as np

from . import effects, presets
from .effects import REGISTRY, make
from .gpu import GPU

PORT = 47128
LINK = Path.home() / ".config" / "badcamera"


def publish():
    """Tell the plugin where this engine is, and what presets exist. Called by the app and the engine at startup."""
    LINK.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        (LINK / "engine").write_text(sys.executable, encoding="utf-8")
    (LINK / "presets.txt").write_text("\n".join(p["name"] for p in presets.load_all()) + "\n", encoding="utf-8")


def recv_all(conn, n):
    buf = bytearray(n)
    view, got = memoryview(buf), 0
    while got < n:
        k = conn.recv_into(view[got:])
        if k == 0:
            raise ConnectionError
        got += k
    return buf


class Engine:
    def __init__(self):
        self.ctx = moderngl.create_standalone_context(backend="egl" if sys.platform.startswith("linux") else None)
        self.g = GPU(self.ctx)
        self.inputs, self.chains = {}, {}

    def chain(self, conn, h):
        """Effect state lives per connection, which is one per plugin instance: temporal effects keep their history, and clips never share it."""
        key = h.get("preset") or h["effect"]
        have = self.chains.get(conn)
        if have is None or have[0] != key:
            if h.get("preset"):
                steps = presets.build(next(p for p in presets.load_all() if p["name"] == h["preset"]))
            else:
                steps = [make(h["effect"])]
            have = self.chains[conn] = (key, steps)
        steps = have[1]
        if h.get("effect"):
            e = steps[0]
            for p in e.params:
                if p.key in h["params"]:
                    v, d = h["params"][p.key], p.default
                    e.v[p.key] = [float(x) for x in v] if isinstance(d, list) else type(d)(v)
            e.error = None
        return steps

    def render(self, conn, h, pixels):
        g, size = self.g, (h["w"], h["h"])
        tex = self.inputs.get(size)
        if tex is None:
            tex = self.inputs[size] = self.ctx.texture(size, 4, dtype="f4")
        tex.write(pixels)
        steps = self.chain(conn, h)
        g.begin_frame(h["time"])
        g.frame = h["frame"]
        effects.rng.seed(h["frame"])
        src = g.run("copy", size=size, tex=tex)
        out = presets.process(g, steps, src)
        errors = [e.error for e in steps if e.error]
        if errors:
            print("[engine]", errors, flush=True)
        return g.fbo(out).read(components=4, dtype="f4", alignment=1)


def serve(port=PORT):
    publish()
    engine = Engine()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))  # loopback only: nothing outside this computer can reach it
    srv.listen(16)
    import select
    conns = [srv]
    idle = 0
    while True:
        ready, _, _ = select.select(conns, [], [], 60)
        idle = idle + 1 if not ready else 0
        if idle >= 30 and len(conns) == 1:  # half an hour with no host attached
            return
        for c in ready:
            if c is srv:
                conn, _ = srv.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conns.append(conn)
                continue
            try:
                n = struct.unpack("<I", recv_all(c, 4))[0]
                h = json.loads(recv_all(c, n))
                if h.get("quit"):
                    return
                data = recv_all(c, h["w"] * h["h"] * 16)
                try:
                    c.sendall(engine.render(c, h, data))
                except Exception as ex:
                    print("[engine]", ex, flush=True)
                    c.sendall(bytes(data))
            except (ConnectionError, OSError, struct.error):
                conns.remove(c)
                engine.chains.pop(c, None)
                c.close()


def manifest():
    """Everything the plugin needs to describe each effect, generated so new effects appear without touching C++."""
    out = []
    for t, cls in sorted(REGISTRY.items()):
        out.append({"type": t, "params": [{"key": p.key, "kind": p.kind, "default": p.default, "lo": p.lo, "hi": p.hi, "options": p.choices() if p.kind == "enum" else None} for p in cls.params]})
    return out
