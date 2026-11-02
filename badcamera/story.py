"""Found-footage tools: damage events, tape age, camera power, handheld motion, story clocks, title cards and CCTV layouts."""
import functools
import hashlib
import json
import math
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from . import text
from .audio import CACHE
from .gpu import DATA
from .output import SR, ffmpeg

# ---- damage events: placed on the timeline, applied after a clip's effects so they hit the tape, not the scene ----

VIDEO_EVENTS = {"Tracking tear": "uTear", "Dropout burst": "uDropout", "Head jump": "uJump", "Signal loss": "uLoss", "Static burst": "uStatic", "Picture roll": "uRoll", "Camera jolt": "uJolt"}
AUDIO_EVENTS = ("Mic overload", "Clipping", "Wind buffet", "Tape slowdown", "Audio dropout")
EVENT_KINDS = list(VIDEO_EVENTS) + list(AUDIO_EVENTS)


def envelope(e, t):
    """0 outside the event, quick rise, hold, quick fall."""
    u = t - e["t"]
    if u < 0 or u > e["d"]:
        return 0.0
    edge = min(0.04, e["d"] / 3)
    return e["amount"] * min(1.0, u / max(edge, 1e-3), (e["d"] - u) / max(edge, 1e-3))


def video_uniforms(events, t):
    out = dict.fromkeys(VIDEO_EVENTS.values(), 0.0)
    for e in events:
        if e["kind"] in VIDEO_EVENTS:
            k = VIDEO_EVENTS[e["kind"]]
            out[k] = max(out[k], envelope(e, t))
    return out


def age_at(tl, t):
    """Tape age here: drifts from the start value to the end value across the whole film."""
    return tl.age_start + (tl.age_end - tl.age_start) * min(max(t / max(tl.duration, 1e-3), 0.0), 1.0)


_rng = np.random.default_rng(7)
_noise = _rng.standard_normal(SR * 8).astype("f4")  # a fixed loop, so noise at a timeline position never changes between playback and export
_wind = np.convolve(_noise, np.ones(600, "f4") / 600, "same")
_wind = (_wind / _wind.std() * 0.1).astype("f4")


def loop(buf, t0, n):
    i = int(round(t0 * SR)) % len(buf)
    return np.take(buf, np.arange(i, i + n), mode="wrap")


def warped_times(t0, n, events):
    """Output time to source time, for tape slowing down: the pitch falls through the event, then playback picks up again."""
    ts = t0 + np.arange(n) / SR
    for e in events:
        if e["kind"] == "Tape slowdown":
            u = (ts - e["t"]) / max(e["d"], 1e-3)
            inside = (u >= 0) & (u <= 1)
            depth = 0.92 * e["amount"]
            ts = np.where(inside, e["t"] + e["d"] * (u - 0.5 * depth * u * u), ts)
    return ts


def apply_audio(x, t0, events, age):
    """Hardware faults on a mixed buffer, in place. Stateless, so any buffer size gives the same result."""
    n = len(x)
    ts = t0 + np.arange(n) / SR
    for e in events:
        if e["kind"] not in AUDIO_EVENTS or e["kind"] == "Tape slowdown" or ts[-1] < e["t"] or ts[0] > e["t"] + e["d"]:
            continue
        env = np.clip(np.minimum((ts - e["t"]) / 0.02, (e["t"] + e["d"] - ts) / 0.02), 0, 1) * e["amount"]
        env = env[:, None]
        if e["kind"] == "Mic overload":  # the capsule and preamp both give up: hard, crunchy, and a lot louder
            x[:] = x * (1 - env) + np.tanh(x * (1 + 30 * env)) * 0.7 * env
        elif e["kind"] == "Clipping":
            limit = 1 - 0.92 * env
            x[:] = np.clip(x * (1 + 6 * env), -limit, limit)
        elif e["kind"] == "Wind buffet":
            w = loop(_wind, t0, n)
            x[:] += (np.tanh(w * 6) * 0.45 * (0.6 + 0.4 * np.sin(ts * 7.3)) * env[:, 0])[:, None]
        elif e["kind"] == "Audio dropout":
            x[:] *= 1 - env
    if age > 0:  # old tape: level wobble and a rising floor
        x *= (1 + 0.04 * age * np.sin(ts * 5.1) * np.sin(ts * 1.3))[:, None]
        x += (loop(_noise, t0, n) * 0.012 * age * age)[:, None]


def thump(ts, at, up=True):
    """The mic catching a power switch: a short low thump, then a little motor whirr as the transport starts."""
    u = ts - at
    y = np.exp(-np.maximum(u, 0) * 22) * np.sin(2 * np.pi * 70 * np.maximum(u, 0)) * 0.35
    if up:
        y += 0.03 * np.exp(-np.maximum(u - 0.1, 0) * 5) * np.sin(2 * np.pi * (300 + 500 * np.minimum(np.maximum(u, 0), 0.4)) * np.maximum(u, 0))
    return (y * (u >= 0)).astype("f4")


# ---- camera power and battery: applied before a clip's effects, because the camera does this ----

def power_state(c, t):
    """Uniforms for power.glsl at source time t. Power-on: dark, then hunting exposure, focus and white balance settling."""
    blur, expose, tint, kill, blink = 0.0, 1.0, 0.0, 0.0, 0.0
    local, left = t - c.start, c.end - t
    if c.power_on and local < 1.6:
        u = local / 1.6
        expose = min(u / 0.1, 1.0) * (1 + 1.5 * math.exp(-u * 4) * (1 + 0.5 * math.sin(local * 11)))
        blur = 14 * (1 - u) ** 2 * (0.55 + 0.45 * math.sin(local * 9))
        tint = (1 - u) ** 2
    if c.power_off and left < 0.35:
        kill = 1 - left / 0.35
    if c.battery:
        blink = 1.0 if left < 5 and (t * 2.5) % 1 < 0.5 else 0.0
        if left < 0.25:
            kill = 1.0  # the battery just dies: no fade, the picture stops
    return dict(uBlur=blur, uExpose=expose, uTint=tint, uKill=kill, uBlink=blink)


# ---- handheld motion ----

MOTIONS = ("None", "Standing", "Walking", "Running", "Panicked", "From video")


def _wobble(t, f, seed):
    return math.sin(t * f + seed) + 0.5 * math.sin(t * f * 2.13 + seed * 1.7) + 0.25 * math.sin(t * f * 4.7 + seed * 0.6)


def motion_at(kind, t, amount, data=None):
    """(dx, dy, roll degrees) as fractions of the frame. Walking has a step rhythm; panic has no rhythm at all."""
    if kind == "Standing":
        m = (0.004 * _wobble(t, 0.9, 1), 0.005 * _wobble(t, 0.7, 2), 0.14 * _wobble(t, 0.5, 3))
    elif kind == "Walking":
        step = abs(math.sin(t * math.pi * 1.8))
        m = (0.012 * math.sin(t * math.pi * 0.9) + 0.004 * _wobble(t, 1.3, 4), 0.016 * step + 0.004 * _wobble(t, 1.1, 5), 0.8 * math.sin(t * math.pi * 0.9) + 0.25 * _wobble(t, 0.8, 6))
    elif kind == "Running":
        step = abs(math.sin(t * math.pi * 2.9))
        m = (0.024 * math.sin(t * math.pi * 1.45) + 0.012 * _wobble(t, 3.1, 7), 0.04 * step ** 3 + 0.012 * _wobble(t, 2.7, 8), 2.2 * math.sin(t * math.pi * 1.45) + 0.9 * _wobble(t, 2.2, 9))
    elif kind == "Panicked":
        jerk = math.sin(t * 3.1) * math.sin(t * 7.7) * math.sin(t * 1.3)
        m = (0.05 * _wobble(t, 6.3, 10) * (0.4 + abs(jerk)), 0.05 * _wobble(t, 5.1, 11) * (0.4 + abs(jerk)), 4.5 * _wobble(t, 4.1, 12) * (0.3 + abs(jerk)))
    elif kind == "From video" and data:
        i = t * data["fps"] % max(len(data["x"]) - 1, 1)
        k, f = int(i), i - int(i)
        pick = lambda a: a[k] * (1 - f) + a[k + 1] * f  # noqa: E731
        m = (pick(data["x"]), pick(data["y"]), pick(data["r"]))
    else:
        return 0.0, 0.0, 0.0
    return m[0] * amount, m[1] * amount, m[2] * amount


def motion_margin(kind, amount):
    """Extra zoom so the moving frame doesn't show its edges."""
    return 1 + amount * {"None": 0.0, "Standing": 0.03, "Walking": 0.07, "Running": 0.14, "Panicked": 0.2, "From video": 0.1}[kind]


def extract_motion(path, done):
    """Measure a real clip's shake (say, from walking with a phone) and keep only the shake, not the deliberate moves."""
    def work():
        try:
            done(motion_from_video(path), None)
        except Exception as ex:
            done(None, str(ex))
    threading.Thread(target=work, daemon=True).start()


def motion_cache(path):
    st = Path(path).stat()
    return CACHE / f"motion_{hashlib.sha1(f'{path}|{st.st_mtime_ns}'.encode()).hexdigest()}.json"


@functools.lru_cache(maxsize=32)
def motion_from_video(path, fps=15.0, width=320):
    out = motion_cache(path)
    if out.exists():
        return json.loads(out.read_text())
    probe = cv2.VideoCapture(str(path))
    w0, h0 = probe.get(cv2.CAP_PROP_FRAME_WIDTH), probe.get(cv2.CAP_PROP_FRAME_HEIGHT)
    probe.release()
    h = max(2, int(width * h0 / max(w0, 1)) & ~1)
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(path), "-an", "-t", "120", "-vf", f"fps={fps},scale={width}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, width)
    xs, ys, rs = [0.0], [0.0], [0.0]
    for a, b in zip(frames, frames[1:]):
        pts = cv2.goodFeaturesToTrack(a, 150, 0.01, 8)
        dx = dy = dr = 0.0
        if pts is not None:
            moved, ok, _ = cv2.calcOpticalFlowPyrLK(a, b, pts, None)
            good = ok.ravel() == 1
            if good.sum() >= 6:
                m, _ = cv2.estimateAffinePartial2D(pts[good], moved[good])
                if m is not None:
                    dx, dy, dr = float(m[0, 2]) / width, -float(m[1, 2]) / h, math.degrees(math.atan2(m[1, 0], m[0, 0]))
        xs.append(xs[-1] + dx)
        ys.append(ys[-1] + dy)
        rs.append(rs[-1] + dr)

    def shake(a):  # subtract a one-second average, leaving the shake and dropping the pans
        a = np.array(a)
        k = int(fps) | 1
        pad = np.pad(a, k, mode="edge")
        return np.round(a - np.convolve(pad, np.ones(k) / k, "same")[k:-k], 5).tolist()
    data = {"fps": fps, "x": shake(xs), "y": shake(ys), "r": shake(rs)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data))
    return data


# ---- story clock ----

def parse_when(s):
    """'1996-07-21 21:14:00' or '1996-07-21 21:14' to an epoch, or None if it can't be read."""
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s.strip(), f))
        except ValueError:
            pass
    return None


def story_starts(tl):
    """Epoch at the start of each main clip. A clip with no date of its own carries on from where the last one stopped."""
    out, now = {}, None
    for c, a, b in tl.layout():
        when = parse_when(c.story) if c.story else None
        now = when if when is not None else now
        out[id(c)] = now
        if now is not None:
            now += b - a
    return out


# ---- title cards ----

CARD_SIZE = (1280, 720)
CARDS = {
    "Evidence tape": ("#101010", "camcorder_osd", "EVIDENCE|CASE NO. 96-4471|TAPE 03 OF 07|DO NOT ERASE"),
    "Case file": ("#000000", "cctv_osd", "POLICE DEPARTMENT|CASE FILE 96-4471|RECOVERED FROM SCENE|%m-%d-%Y"),
    "Deck blue": ("#0a1ab8", "vcr_osd", "TAPE 03"),
    "Warning": ("#000000", "cctv_osd", "THE FOLLOWING FOOTAGE|WAS RECOVERED INTACT|VIEWER DISCRETION ADVISED"),
    "Black": ("#000000", "camcorder_osd", ""),
}


def make_card(name, lines, seconds, when=None):
    """Render a card to a short silent video, so it behaves like any other clip: it can be cut, degraded and bundled."""
    bg, style, _ = CARDS[name]
    w, h = CARD_SIZE
    rgb = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    img = np.full((h, w, 3), rgb, np.uint8)
    t = time.strftime(lines, time.localtime(when)) if "%" in lines else lines
    rows = [r.strip() for r in t.split("|") if r.strip()]
    if rows:
        rgba, _ = text.render(h, rows, style, "DejaVu Sans Bold", 2.0, [1, 1, 1], 0.0, 0.0, 0.9, 0.0, 0.0, "center")
        th, tw = rgba.shape[:2]
        x, y = (w - tw) // 2, (h - th) // 2
        a = rgba[..., 3:] / 255
        img[y:y + th, x:x + tw] = rgba[..., :3] * a + img[y:y + th, x:x + tw] * (1 - a)
    folder = DATA / "captures" / "cards"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{name.lower().replace(' ', '_')}_{hashlib.sha1((lines + str(seconds) + bg).encode()).hexdigest()[:8]}"
    png, out = folder / f"{stem}.png", folder / f"{stem}.mp4"
    cv2.imwrite(str(png), img[..., ::-1])
    subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-loop", "1", "-r", "30", "-i", str(png), "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo", "-t", f"{seconds:.2f}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "15", "-c:a", "aac", "-shortest", str(out)], check=True)
    png.unlink()
    return out


# ---- the realism pass and scare moments ----

def realism_pass(tl, seed, density):
    """Scatter small faults across the film so nothing feels too regular. The same seed gives the same result, and it replaces its earlier run."""
    rng = np.random.default_rng(seed)
    tl.events = [e for e in tl.events if not e.get("auto")]
    t = float(rng.exponential(12 / max(density, 0.05)))
    while t < tl.duration:
        kind = str(rng.choice(["Dropout burst", "Dropout burst", "Tracking tear", "Head jump", "Audio dropout"], p=[0.35, 0.3, 0.15, 0.1, 0.1]))
        tl.events.append({"t": round(t, 3), "d": round(float(rng.uniform(0.05, 0.5)), 3), "kind": kind, "amount": round(float(rng.uniform(0.2, 0.6)), 3), "auto": True})
        t += float(rng.exponential(12 / max(density, 0.05)))
    tl.events.sort(key=lambda e: e["t"])


def add_scare(tl, t, strength=1.0):
    """One moment: a jolt and a tape fault that hit together."""
    tl.events += [{"t": t, "d": 0.45, "kind": "Camera jolt", "amount": strength}, {"t": t, "d": 0.14, "kind": "Static burst", "amount": 0.7 * strength},
                  {"t": t + 0.03, "d": 0.3, "kind": "Head jump", "amount": 0.6 * strength}]
    tl.events.sort(key=lambda e: e["t"])


# ---- script import ----

HEADING = __import__("re").compile(r"^(?:\.(?=[A-Z])|(?:INT|EXT|EST|I/E|INT/EXT)[\. ]).*", __import__("re").I)


def parse_script(text_):
    """Scene headings from a Fountain or plain-text screenplay."""
    scenes = []
    for line in text_.splitlines():
        t = line.strip()
        if HEADING.match(t) and t == t.upper():
            scenes.append({"n": len(scenes) + 1, "title": t.lstrip(".")})
    return scenes
