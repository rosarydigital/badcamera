"""Small video editor: clips on one timeline, each with its own effects, transform and audio, rendered by the same GPU chain as the camera."""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np

from . import audio, effects, exchange, presets, sound, story, transform
from .effects import make
from .gpu import DATA
from .output import CAPTURES, SR, ffmpeg, probe, stamp_path

TRANSITIONS = ["Cut", "Crossfade", "Fade to black", "Tape rewind", "Tape pause", "Tape stop"]
H264 = ("-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-threads", "1", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart")
YOUTUBE = ("-c:v", "libx264", "-preset", "slow", "-crf", "15", "-pix_fmt", "yuv420p", "-threads", "1", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart")
PRORES = ("-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-c:a", "pcm_s24le")
# size None follows the first clip. picture: the shape inside the frame, for a 4:3 master in a 16:9 container.
FORMATS = {
    "Same as first clip": dict(size=None, fps=None, args=H264, ext="mp4"),
    "NTSC 640x480 29.97": dict(size=(640, 480), fps=30000 / 1001, args=H264, ext="mp4"),
    "PAL 768x576 25": dict(size=(768, 576), fps=25.0, args=H264, ext="mp4"),
    "HD 1280x720 30": dict(size=(1280, 720), fps=30.0, args=H264, ext="mp4"),
    "YouTube 1080p 30": dict(size=(1920, 1080), fps=30.0, args=YOUTUBE, ext="mp4"),
    "ProRes master 1080p 24": dict(size=(1920, 1080), fps=24.0, args=PRORES, ext="mov"),
    "ProRes 4:3 in 16:9, 24": dict(size=(1920, 1080), fps=24.0, args=PRORES, ext="mov", picture=(1440, 1080)),
    "ProRes 2K flat for DCP, 24": dict(size=(1998, 1080), fps=24.0, args=PRORES, ext="mov"),
}
VARIANTS = ("As edited", "Clean (no effects)", "Aged")
AUTOSAVE = DATA / "autosave.bcproj"
VIDEO_TYPES = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".3gp", ".ts", ".mts", ".m2ts")
MAX_SIDE = 1920


class Tx:
    """A transform plus its keyframes, shaped like an Effect so the same keyframe code handles both."""

    def __init__(self, v=None, keys=None):
        self.v, self.keys = transform.new(v), keys or {}


def interp(pts, t):
    """Linear interpolation through sorted [time, value] keyframes, holding the ends."""
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / max(t1 - t0, 1e-9)
    return pts[-1][1]


def apply_keys(obj, t):
    for key, pts in getattr(obj, "keys", {}).items():
        if pts:
            obj.v[key] = type(obj.v[key])(interp(pts, t))


def set_key(obj, key, t, value):
    """Add or move the keyframe at time t."""
    pts = obj.keys.setdefault(key, [])
    for p in pts:
        if abs(p[0] - t) < 1 / 240:
            p[1] = value
            return
    pts.append([t, value])
    pts.sort()


def key_at(obj, key, t):
    return next((p for p in obj.keys.get(key, []) if abs(p[0] - t) < 1 / 240), None)


def toggle_key(obj, key, t):
    p = key_at(obj, key, t)
    if p:
        obj.keys[key].remove(p)
        if not obj.keys[key]:
            del obj.keys[key]
    else:
        set_key(obj, key, t, obj.v[key])


def clone_steps(steps):
    out = []
    for e in steps:
        n = make(e.type, e.v, e.enabled)
        n.keys = copy.deepcopy(getattr(e, "keys", {}))
        out.append(n)
    return out


class Clip:
    EXTRA = ("story", "note", "denoise", "power_on", "power_off", "battery", "motion", "motion_amount", "motion_file", "at", "rect", "opacity", "space", "sync_path", "sync_offset", "scene")

    def __init__(self, path, info, start=0.0, end=None):
        self.path, self.info = str(path), info
        self.start, self.end = start, info["duration"] if end is None else end
        self.steps, self.tx = [], Tx()
        self.audio, self.gain, self.mute, self.wet, self.noise = audio.ORIGINAL, 1.0, False, 1.0, 1.0
        self.auto_audio = True  # picking a video preset also picks its matching audio until the user chooses one by hand
        self.preset_name, self.trans, self.trans_d = "None", "Cut", 0.5
        self.story, self.note, self.denoise = "", "", "Off"
        self.power_on, self.power_off, self.battery = False, False, False
        self.motion, self.motion_amount, self.motion_file = "None", 1.0, ""
        self.at, self.rect, self.opacity = 0.0, [0.0, 0.0, 1.0, 1.0], 1.0  # used on the overlay track
        self.space, self.sync_path, self.sync_offset, self.scene = "None", "", 0.0, 0

    @property
    def length(self):
        return self.end - self.start

    @property
    def name(self):
        return Path(self.path).name

    def to_json(self):
        return {"path": self.path, "start": self.start, "end": self.end, "steps": [{**e.to_json(), "keys": getattr(e, "keys", {})} for e in self.steps],
                "transform": self.tx.v, "transform_keys": self.tx.keys, "audio": self.audio, "gain": self.gain, "mute": self.mute, "wet": self.wet, "noise": self.noise,
                "auto_audio": self.auto_audio, "preset": self.preset_name, "trans": self.trans, "trans_d": self.trans_d,
                **{k: getattr(self, k) for k in self.EXTRA}}

    @classmethod
    def from_json(cls, d, info=None, base=None):
        path = Path(d["path"])
        if base and not path.is_absolute():
            path = base / path
        c = cls(path, info or probe(path), d["start"], d["end"])
        c.steps = [make(s["type"], s.get("params"), s.get("enabled", True)) for s in d["steps"]]
        for e, s in zip(c.steps, d["steps"]):
            e.keys = s.get("keys", {})
        c.tx = Tx(d["transform"], d.get("transform_keys"))
        c.audio, c.gain, c.mute, c.wet, c.noise = d["audio"], d["gain"], d["mute"], d["wet"], d.get("noise", 1.0)
        c.auto_audio, c.preset_name, c.trans, c.trans_d = d.get("auto_audio", True), d.get("preset", "None"), d["trans"], d["trans_d"]
        for k in cls.EXTRA:
            if k in d:
                setattr(c, k, d[k])
        return c


MATCH = "Match clip"  # a sound takes on the hardware of whatever clip it's over, so it sounds recorded there
SOUND_TRACKS = ("Ambience", "Effects", "Music")


class Sound:
    """A clip on the sound track, for room tone, ambience or effects. Plays under the video's own audio, wherever it's placed."""

    def __init__(self, path, info, at=0.0):
        self.path, self.info, self.at = str(path), info, at
        self.start, self.end, self.audio, self.gain, self.noise, self.mute = 0.0, info["duration"], MATCH, 0.6, 1.0, False
        self.track, self.fade_in, self.fade_out, self.space, self.points = 0, 0.25, 0.25, "None", []  # points: [source time, gain] volume keyframes

    @property
    def name(self):
        return Path(self.path).name

    @property
    def length(self):
        return self.end - self.start

    def to_json(self):
        return {k: getattr(self, k) for k in ("path", "at", "start", "end", "audio", "gain", "noise", "mute", "track", "fade_in", "fade_out", "space", "points")}

    @classmethod
    def from_json(cls, d, info=None):
        s = cls(d["path"], info or probe(d["path"], need_video=False))
        for k, v in d.items():
            setattr(s, k, v)
        return s


class Timeline:
    def __init__(self):
        self.clips, self.fmt = [], list(FORMATS)[0]
        self.overlays, self.sounds, self.events, self.markers = [], [], [], []
        self.age_start, self.age_end = 0.0, 0.0
        self.master, self.scenes, self.reels = 0.0, [], {}
        self.undo_stack, self.redo_stack = [], []
        self.saved_state = self.state()

    def state(self):
        return json.dumps({"clips": [c.to_json() for c in self.clips], "fmt": self.fmt, "overlays": [c.to_json() for c in self.overlays],
                           "sounds": [c.to_json() for c in self.sounds], "events": self.events, "markers": self.markers,
                           "age": [self.age_start, self.age_end], "master": self.master, "scenes": self.scenes}, sort_keys=True)

    def load(self, d, infos=None):
        infos = infos or {}
        self.clips, self.fmt = [Clip.from_json(c, infos.get(c["path"])) for c in d["clips"]], d.get("fmt", list(FORMATS)[0])
        self.overlays = [Clip.from_json(c, infos.get(c["path"])) for c in d.get("overlays", [])]
        self.sounds = [Sound.from_json(c, infos.get(c["path"])) for c in d.get("sounds", [])]
        self.events, self.markers = d.get("events", []), d.get("markers", [])
        self.age_start, self.age_end = d.get("age", [0.0, 0.0])
        self.master, self.scenes = d.get("master", 0.0), d.get("scenes", [])

    def infos(self):
        return {c.path: c.info for c in self.clips + self.overlays + self.sounds}

    def restore(self, state):
        self.load(json.loads(state), self.infos())
        self.saved_state = state

    def commit(self):
        """Record an undo step if anything changed since the last one."""
        now = self.state()
        if now != self.saved_state:
            self.undo_stack.append(self.saved_state)
            del self.undo_stack[:-200]
            self.redo_stack.clear()
            self.saved_state = now
            return True
        return False

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.saved_state)
            self.restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.saved_state)
            self.restore(self.redo_stack.pop())

    def overlap(self, i):
        """Seconds clip i overlaps the next one (its transition length, kept to half the shorter clip)."""
        if i + 1 >= len(self.clips) or self.clips[i].trans == "Cut":
            return 0.0
        return min(self.clips[i].trans_d, self.clips[i].length / 2, self.clips[i + 1].length / 2)

    def layout(self):
        """[(clip, start, end)] on the timeline."""
        out, t = [], 0.0
        for i, c in enumerate(self.clips):
            out.append((c, t, t + c.length))
            t += c.length - self.overlap(i)
        return out

    @property
    def duration(self):
        """The picture sets the length. A long room tone just stops when the film does."""
        lay = self.layout()
        ends = ([lay[-1][2]] if lay else []) + [c.at + c.length for c in self.overlays]
        return max(ends or [s.at + s.length for s in self.sounds], default=0.0)

    def overlays_at(self, t):
        return [(c, c.start + t - c.at) for c in self.overlays if c.at <= t < c.at + c.length]

    def at(self, t):
        """What's showing at time t: [(clip, source time)] (two during a transition) and the transition progress."""
        t = min(max(t, 0.0), max(self.duration - 1e-6, 0.0))
        lay = self.layout()
        for i, (c, a, b) in enumerate(lay):
            if a <= t < b:
                if i + 1 < len(lay) and t >= lay[i + 1][1]:
                    n, a2, _ = lay[i + 1]
                    return [(c, c.start + t - a), (n, n.start + t - a2)], (t - a2) / max(b - a2, 1e-9), c.trans
                return [(c, c.start + t - a)], 0.0, "Cut"
        return [], 0.0, "Cut"

    def index_at(self, t):
        for i, (_, a, b) in enumerate(self.layout()):
            if a <= t < b:
                return i
        return len(self.clips) - 1

    def split(self, t):
        """Cut the clip under the playhead in two. Returns the new right-hand clip's index, or None if too close to an edge."""
        i = self.index_at(t)
        if i < 0:
            return None
        c, a, _ = self.layout()[i]
        at = c.start + t - a
        if at - c.start < 0.05 or c.end - at < 0.05:
            return None
        right = Clip.from_json(c.to_json(), c.info)
        c.end, right.start = at, at
        c.trans = "Cut"
        self.clips.insert(i + 1, right)
        return i + 1

    def split_item(self, items, c, t, factory):
        """Cut an overlay or sound at timeline time t into two pieces on the same track."""
        at = c.start + t - c.at
        if at - c.start < 0.05 or c.end - at < 0.05:
            return None
        right = factory(c)
        c.end, right.start, right.at = at, at, t
        items.insert(items.index(c) + 1, right)
        return items.index(right)

    def delete(self, i):
        self.clips.pop(i)

    def move(self, i, j):
        self.clips.insert(j, self.clips.pop(i))

    def trim(self, i, start=None, end=None):
        c = self.clips[i]
        if start is not None:
            c.start = min(max(start, 0.0), c.end - 0.05)
        if end is not None:
            c.end = max(min(end, c.info["duration"]), c.start + 0.05)

    def format(self):
        """(width, height), fps for the project."""
        f = FORMATS[self.fmt]
        if f["size"]:
            return f["size"], f["fps"]
        if not self.clips:
            return (1280, 720), 30.0
        (w, h), fps = fit_size(self.clips[0].info["size"]), self.clips[0].info["fps"]
        return (w, h), min(fps, 60.0)

    def mix(self, worker, t0, n, parts=("main", "sound"), noise=None, faults=True):
        """n stereo float frames starting at timeline time t0: shared by playback and export so they can't differ.
        parts picks tracks, noise overrides the clips' tape noise (for stems), faults applies the audio damage events."""
        slow = [e for e in self.events if e["kind"] == "Tape slowdown" and e["t"] < t0 + n / SR and e["t"] + e["d"] > t0] if faults else []
        if slow:
            ts = story.warped_times(t0, n, slow)
            lo = float(ts.min())
            m = int((float(ts.max()) - lo) * SR) + 3
            raw = self.tracks(worker, lo, m, parts, noise)
            x = (ts - lo) * SR
            out = np.stack([np.interp(x, np.arange(m), raw[:, ch]) for ch in (0, 1)], axis=1).astype("f4")
        else:
            out = self.tracks(worker, t0, n, parts, noise)
        if faults:
            story.apply_audio(out, t0, self.events, story.age_at(self, t0))
        if self.master:
            out *= 10 ** (self.master / 20)
        return out

    def preset_of(self, s):
        """The hardware a sound goes through: its own, or the clip it's over."""
        if s.audio != MATCH:
            return s.audio
        shown = self.at(s.at)[0]
        return shown[0][0].audio if shown else audio.ORIGINAL

    def tracks(self, worker, t0, n, parts, noise):
        out = np.zeros((n, 2), "f4")
        ts = t0 + np.arange(n) / SR
        if "main" in parts:
            for i, (c, a, b) in enumerate(self.layout()):
                if c.mute or b <= t0 or a >= t0 + n / SR:
                    continue
                self.add_clip(out, worker, c, a, b, t0, n, c.info["audio"], self.overlap(i), self.overlap(i - 1) if i else 0.0,
                              self.clips[i - 1].trans if i else "Cut", noise)
                for at, on, up in ((a, c.power_on, True), (b - 0.35, c.power_off, False), (b - 0.25, c.battery, False)):
                    if on and at - 0.01 < t0 + n / SR and at + 0.5 > t0:
                        out += (story.thump(ts, at, up) * c.gain)[:, None]
            for c in self.overlays:
                if not c.mute and c.at < t0 + n / SR and c.at + c.length > t0:
                    self.add_clip(out, worker, c, c.at, c.at + c.length, t0, n, c.info["audio"], 0.0, 0.0, "Cut", noise)
        if "sound" in parts:
            for c in self.sounds:
                if not c.mute and c.at < t0 + n / SR and c.at + c.length > t0:
                    self.add_clip(out, worker, c, c.at, c.at + c.length, t0, n, True, 0.0, 0.0, "Cut", noise)
        return out

    def add_clip(self, out, worker, c, a, b, t0, n, has_audio, over_out, over_in, trans_in, noise):
        """Add one clip's sound to out, with its gain, wet mix and transition or edge fades."""
        if not has_audio and not getattr(c, "sync_path", ""):
            return
        denoise, wet_mix, room = getattr(c, "denoise", "Off"), getattr(c, "wet", 1.0), c.space
        path, shift = getattr(c, "sync_path", "") or c.path, getattr(c, "sync_offset", 0.0) if getattr(c, "sync_path", "") else 0.0
        preset = self.preset_of(c) if isinstance(c, Sound) else c.audio
        dry = worker.pcm(path, audio.ORIGINAL, 1.0, denoise, room)
        amount = c.noise if noise is None else noise
        wet = dry if preset == audio.ORIGINAL else worker.pcm(path, preset, amount, denoise, room)
        if dry is None:
            return
        wet = dry if wet is None else wet  # effect still rendering: play it clean rather than go silent
        first = max(int(round((a - t0) * SR)), 0)
        count = min(n - first, int(round((b - t0) * SR)) - first)
        src = int(round((c.start + shift + t0 - a) * SR)) + first
        src0 = max(src, 0)
        first += src0 - src
        count = min(count - (src0 - src), len(dry) - src0, len(wet) - src0)
        if count <= 0:
            return
        x = wet[src0:src0 + count].astype("f4") / 32768
        if preset != audio.ORIGINAL and wet_mix < 1:
            x = x * wet_mix + dry[src0:src0 + count].astype("f4") / 32768 * (1 - wet_mix)
        x *= c.gain
        ts = t0 + (first + np.arange(count)) / SR
        g = np.ones(count, "f4")
        trans = getattr(c, "trans", "Cut")
        if over_out:
            p = np.clip((ts - (b - over_out)) / over_out, 0, 1)
            g *= np.cos(p * np.pi / 2) if trans == "Crossfade" else np.clip(1 - 2 * p, 0, 1)
        if over_in:
            p = np.clip((ts - a) / over_in, 0, 1)
            g *= np.sin(p * np.pi / 2) if trans_in == "Crossfade" else np.clip(2 * p - 1, 0, 1)
        if isinstance(c, Sound):
            g *= np.clip(np.minimum((ts - a) / max(c.fade_in, 1e-3), (b - ts) / max(c.fade_out, 1e-3)), 0, 1)
            if c.points:
                pts = sorted(c.points)
                g *= np.interp(c.start + ts - a, [q[0] for q in pts], [q[1] for q in pts]).astype("f4")
        out[first:first + count] += x * g[:, None]

    def audio_keys(self, noise=None):
        """Every cached render an export of this project needs."""
        keys = set()
        for c in self.clips + self.overlays:
            path = c.sync_path or c.path
            if c.info["audio"] or c.sync_path:
                keys |= {(path, audio.ORIGINAL, 1.0, c.denoise, c.space), (path, c.audio, c.noise if noise is None else noise, c.denoise, c.space)}
        for c in self.sounds:
            keys |= {(c.path, audio.ORIGINAL, 1.0, "Off", c.space), (c.path, self.preset_of(c), c.noise if noise is None else noise, "Off", c.space)}
        return keys


def fit_size(size):
    w, h = size
    k = min(1.0, MAX_SIDE / max(w, h))
    return max(2, int(w * k) & ~1), max(2, int(h * k) & ~1)


def decode_size(info, project):
    """Decode no larger than the project needs, keeping the source's shape."""
    (w, h), (pw, ph) = info["size"], project
    k = min(1.0, pw / w, ph / h) if (w > pw or h > ph) else 1.0
    return max(2, int(w * k) & ~1), max(2, int(h * k) & ~1)


def open_reader(path, t, size, fps):
    return subprocess.Popen(
        [ffmpeg(), "-loglevel", "quiet", "-nostdin", "-ss", f"{t:.4f}", "-i", path, "-an", "-sn", "-vf", f"fps={fps:.6f},scale={size[0]}:{size[1]}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)


class Decoder(threading.Thread):
    """Keeps the wanted frame ready for preview. It reads ahead and remembers recent frames, so scrubbing nearby doesn't need a new ffmpeg."""
    KEEP, AHEAD = 180, 24

    def __init__(self):
        super().__init__(daemon=True)
        self.want, self.frame, self.seq, self.running, self.proc = None, None, 0, True, None
        self.start()

    def seek(self, path, t, size, fps):
        self.want = (path, t, size, fps)

    def run(self):
        current, frames, next_i, size, shown = None, {}, 0, None, None
        while self.running:
            want = self.want
            if want is None:
                time.sleep(0.005)
                continue
            path, t, want_size, fps = want
            key = (path, want_size, fps)
            i = int(t * fps + 1e-6)
            if key != current:
                current, frames, size, shown = key, {}, want_size, None
                self.close()
            if i in frames:
                if i != shown:
                    self.frame, self.seq, shown = frames[i], self.seq + 1, i
            elif self.proc is None or i < next_i or i > next_i + int(fps):  # too far to read forward: start ffmpeg here
                self.close()
                self.proc, next_i = open_reader(path, i / fps, size, fps), i
            n = size[0] * size[1] * 3
            if self.proc is not None and (i >= next_i or next_i <= i + self.AHEAD):
                raw = self.proc.stdout.read(n)
                if len(raw) < n:  # end of file: hold what we have until the next seek
                    self.close()
                    if i not in frames and frames:
                        i0 = max(frames)
                        frames[i] = frames[i0]
                    time.sleep(0.01)
                    continue
                frames[next_i] = np.frombuffer(raw, np.uint8).reshape(size[1], size[0], 3)
                next_i += 1
                for k in sorted(frames, key=lambda k: -abs(k - i))[:max(0, len(frames) - self.KEEP)]:
                    del frames[k]
            else:
                time.sleep(0.002)

    def close(self):
        if self.proc:
            self.proc.kill()
            self.proc.wait()
            self.proc = None

    def stop(self):
        self.running = False
        self.join(timeout=1)
        self.close()


class Proxies(threading.Thread):
    """Makes small all-intra stand-ins for long or large files, which seek instantly. Export always uses the originals."""
    SIZE = (854, 480)

    def __init__(self):
        super().__init__(daemon=True)
        self.q, self.ready, self.pending = [], {}, set()
        self.start()

    def path_for(self, path):
        st = Path(path).stat()
        name = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()
        return audio.CACHE / f"proxy_{name}.avi"

    def want(self, c):
        """The file to preview for this clip, starting a proxy if the clip is big enough to need one."""
        if c.path in self.ready:
            return self.ready[c.path]
        w, h = c.info["size"]
        if c.path not in self.pending and (h > 720 or c.info["duration"] > 120):
            out = self.path_for(c.path)
            if out.exists():
                self.ready[c.path] = str(out)
                return self.ready[c.path]
            self.pending.add(c.path)
            self.q.append((c.path, out))
        return c.path

    def run(self):
        while True:
            if not self.q:
                time.sleep(0.1)
                continue
            path, out = self.q.pop(0)
            out.parent.mkdir(parents=True, exist_ok=True)
            part = out.with_name(out.name + ".part.avi")
            r = subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-nostdin", "-i", path, "-an", "-vf", f"scale={self.SIZE[0]}:{self.SIZE[1]}:force_original_aspect_ratio=decrease,"
                                "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "mjpeg", "-q:v", "6", str(part)])
            if r.returncode == 0:
                part.replace(out)
                self.ready[path] = str(out)
            else:
                part.unlink(missing_ok=True)
            self.pending.discard(path)


class Reader:
    """Sequential blocking frames for export."""

    def __init__(self, clip, project_size, fps):
        self.size = decode_size(clip.info, project_size)
        self.proc = open_reader(clip.path, clip.start, self.size, fps)
        self.last = None

    def next(self):
        n = self.size[0] * self.size[1] * 3
        raw = self.proc.stdout.read(n)
        if len(raw) == n:
            self.last = raw
        return self.last

    def close(self):
        self.proc.kill()
        self.proc.wait()


def moved(clip, t):
    """The clip's transform, with handheld motion added on top."""
    if clip.motion == "None":
        return clip.tx.v
    data = story.motion_from_video(clip.motion_file) if clip.motion == "From video" and clip.motion_file else None
    dx, dy, roll = story.motion_at(clip.motion, t, clip.motion_amount, data)
    v = dict(clip.tx.v)
    v["move_x"] += dx
    v["move_y"] += dy
    v["rotate"] += roll
    v["zoom"] *= story.motion_margin(clip.motion, clip.motion_amount)
    return v


def render_clip(g, clip, frame_tex, size, t, bypass=False, epoch=None):
    """One source frame through the clip's transform and effects at source time t."""
    apply_keys(clip.tx, t)
    for e in clip.steps:
        apply_keys(e, t)
    src = g.run("ingest", size=size, tex=frame_tex, uTransformed=1, uXform=transform.matrix(moved(clip, t), size, frame_tex.size))
    if clip.power_on or clip.power_off or clip.battery:
        src = g.run("power", size=size, tex=src, **story.power_state(clip, t))
    if bypass:
        return src
    wall, g.wall = g.wall, g.wall if epoch is None else epoch + t - clip.start  # on-screen clocks show the story's time
    out = presets.process(g, clip.steps, src)
    g.wall = wall
    return out


def composite(g, shown, p, kind, size):
    """shown: list of output textures (one, or two during a transition)."""
    if len(shown) == 1:
        return shown[0]
    return g.run("transition", size=size, tex=shown[0], uB=shown[1], uP=float(p), uKind=TRANSITIONS.index(kind))


def render_timeline(g, tl, t, frame_for, size, bypass=False):
    """The whole picture at time t: main track, overlays, then damage. frame_for gives a source frame's texture for a clip."""
    parts, p, kind = tl.at(t)
    starts = story.story_starts(tl)
    shown = []
    for slot, (clip, src_t) in enumerate(parts):
        tex = frame_for(clip, src_t, slot)
        if tex is not None:
            shown.append(render_clip(g, clip, tex, size, src_t, bypass, starts.get(id(clip))))
    black = g.tmp(*size)
    g.fbo(black).clear()
    out = composite(g, shown, p, kind, size) if shown else black
    for slot, (clip, src_t) in enumerate(tl.overlays_at(t), 2):
        tex = frame_for(clip, src_t, slot)
        if tex is None:
            continue
        x, y, w, h = clip.rect
        rect_size = (max(2, int(size[0] * w)), max(2, int(size[1] * h)))
        when = story.parse_when(clip.story) if clip.story else None
        top = render_clip(g, clip, tex, rect_size, src_t, bypass, when)
        out = g.run("layer", size=size, tex=out, uTop=top, uRect=(x, 1 - y - h, w, h), uOpacity=clip.opacity)
    age = story.age_at(tl, t)
    faults = story.video_uniforms(tl.events, t)
    if bypass or not (age or any(faults.values())):
        return out
    return g.run("damage", size=size, tex=out, uAge=age, uSeed=(g.frame * 0.618034) % 1, **faults)


class Exporter:
    """Renders the timeline frame by frame. Time comes from the frame number, not the clock, so two exports match."""

    def __init__(self, tl, worker, path=None, epoch=None, variant="As edited"):
        self.tl, self.worker = self.copy(tl, variant), worker
        self.fmt = FORMATS[tl.fmt]
        self.size, self.fps = self.tl.format()
        self.path = Path(path) if path else stamp_path(self.fmt["ext"])
        self.n, self.total, self.name = 0, max(1, int(round(self.tl.duration * self.fps))), self.path.name
        self.epoch = time.time() if epoch is None else epoch  # on-screen dates advance with the render, not the wall clock
        self.readers, self.textures, self.proc, self.error, self.done = {}, {}, None, None, False
        self.audio_path = self.path.with_suffix(".export.wav")
        self.audio_ready = False
        threading.Thread(target=self.write_audio, daemon=True).start()

    @staticmethod
    def copy(tl, variant="As edited"):
        """A private copy with fresh effect state, so later edits don't touch a running export."""
        t = Timeline()
        t.load(json.loads(tl.state()), tl.infos())
        if variant == "Clean (no effects)":
            t.events, t.age_start, t.age_end = [], 0.0, 0.0
            for c in t.clips + t.overlays:
                c.steps, c.audio = [], audio.ORIGINAL
        elif variant == "Aged":
            t.age_start, t.age_end = max(t.age_start, 0.3), 1.0
        return t

    def write_audio(self):
        try:
            self.worker.wait(self.tl.audio_keys())
            write_wav(self.audio_path, self.tl, self.worker)
            self.audio_ready = True
        except Exception as ex:
            self.error = str(ex)

    def start_encoder(self):
        w, h = self.size
        self.proc = subprocess.Popen(
            [ffmpeg(), "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", f"{self.fps:.6f}", "-i", "-",
             "-i", str(self.audio_path), *self.fmt["args"], "-shortest", str(self.path)], stdin=subprocess.PIPE)
        effects.rng.seed(1234)

    def frame_for(self, g):
        def get(clip, src_t, slot):
            reader = self.readers.get(id(clip))
            if reader is None:
                reader = self.readers[id(clip)] = Reader(clip, self.inner, self.fps)
            raw = reader.next()
            if raw is None:
                return None
            tex = self.textures.get(reader.size)
            if tex is None:
                tex = self.textures[reader.size] = g.ctx.texture(reader.size, 3, alignment=1)
            tex.write(raw)
            return tex
        return get

    @property
    def inner(self):
        return self.fmt.get("picture", self.size)

    def step(self, g, budget=0.03):
        """Render frames for up to `budget` seconds. Returns True when finished."""
        if self.error or self.done:
            return True
        if not self.audio_ready:
            return False
        if self.proc is None:
            self.start_encoder()
        t0 = time.perf_counter()
        while self.n < self.total and time.perf_counter() - t0 < budget:
            t = self.n / self.fps
            g.begin_frame(t)
            g.frame, g.wall = self.n, self.epoch + t
            out = render_timeline(g, self.tl, t, self.frame_for(g), self.inner)
            if self.inner != self.size:  # a 4:3 picture centred in a wider frame
                black = g.tmp(*self.size)
                g.fbo(black).clear()
                w = self.inner[0] / self.size[0]
                out = g.run("layer", size=self.size, tex=black, uTop=out, uRect=((1 - w) / 2, 0.0, w, 1.0), uOpacity=1.0)
            self.proc.stdin.write(g.read(out).tobytes())
            self.n += 1
            showing = {id(c) for c, _ in self.tl.at(t)[0]} | {id(c) for c, _ in self.tl.overlays_at(t)}
            for key in [k for k in self.readers if k not in showing]:
                self.readers.pop(key).close()
        g.wall = None
        if self.n >= self.total:
            self.finish()
            return True
        return False

    def finish(self):
        for r in self.readers.values():
            r.close()
        self.proc.stdin.close()
        if self.proc.wait():
            self.error = "ffmpeg couldn't finish the export"
        self.audio_path.unlink(missing_ok=True)
        self.done = True

    def cancel(self):
        for r in self.readers.values():
            r.close()
        if self.proc:
            self.proc.kill()
            self.proc.wait()
        self.error = "Export cancelled"
        self.audio_path.unlink(missing_ok=True)
        self.path.unlink(missing_ok=True)


def write_wav(path, tl, worker, **mix):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        t = 0.0
        while t < tl.duration:
            n = min(SR, int(round((tl.duration - t) * SR)))
            if n <= 0:
                break
            w.writeframes((np.clip(tl.mix(worker, t, n, **mix), -1, 1) * 32767).astype("i2").tobytes())
            t += n / SR


def export_stems(tl, worker, folder):
    """Separate tracks for a sound mixer. dialogue + noise + sound equals the full mix, so nothing is lost or doubled."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    t = Exporter.copy(tl)
    t.master = 0.0  # stems stay at their working level; the mixer sets the final one
    worker.wait(t.audio_keys() | t.audio_keys(noise=0.0))
    write_wav(folder / "dialogue.wav", t, worker, parts=("main",), noise=0.0)
    write_wav(folder / "sound.wav", t, worker, parts=("sound",))
    write_wav(folder / "full_mix.wav", t, worker)
    with wave.open(str(folder / "full_mix.wav")) as a, wave.open(str(folder / "dialogue.wav")) as d, wave.open(str(folder / "sound.wav")) as b, wave.open(str(folder / "noise.wav"), "wb") as out:
        out.setparams(a.getparams())
        while (full := a.readframes(SR)):
            x = np.frombuffer(full, "i2").astype("i4") - np.frombuffer(d.readframes(SR), "i2") - np.frombuffer(b.readframes(SR), "i2")
            out.writeframes(np.clip(x, -32768, 32767).astype("i2").tobytes())
    return folder


class Thumbs(threading.Thread):
    """Makes a filmstrip per file in the background; the UI thread uploads it."""
    W, H, N = 64, 36, 16

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.jobs, self.ready = [], {}
        self.start()

    def add(self, path, duration):
        with self.lock:
            self.jobs.append((path, duration))

    def run(self):
        while True:
            with self.lock:
                job = self.jobs.pop() if self.jobs else None
            if job is None:
                time.sleep(0.05)
                continue
            path, dur = job
            rate = self.N / max(dur, 0.1)
            r = subprocess.run([ffmpeg(), "-loglevel", "quiet", "-nostdin", "-skip_frame", "nokey" if dur > 60 else "default", "-i", path, "-an", "-vf",
                                f"fps={rate:.6f},scale={self.W}:{self.H}", "-frames:v", str(self.N), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                               capture_output=True)
            n = len(r.stdout) // (self.W * self.H * 4)
            if n:
                self.ready[path] = (n, np.frombuffer(r.stdout[:n * self.W * self.H * 4], np.uint8).reshape(n * self.H, self.W, 4).copy())


# ---- project files ----

def save_project(tl, path, relative_to=None):
    d = json.loads(tl.state())
    d["reels"] = tl.reels
    if relative_to:
        for c in d["clips"] + d["overlays"] + d["sounds"]:
            c["path"] = os.path.relpath(c["path"], relative_to)
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps({"app": "badcamera", "version": 1, **d}, indent=1), encoding="utf-8")
    tmp.replace(path)  # never leaves a half-written project behind


def load_project(tl, path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    base, clips, missing = Path(path).resolve().parent, [], []
    for c in d["clips"]:
        p = Path(c["path"])
        p = p if p.is_absolute() else base / p
        if p.exists():
            clips.append(Clip.from_json({**c, "path": str(p)}))
        else:
            missing.append(p.name)
    tl.load({"overlays": [], "sounds": [], "clips": [], **d, **{"clips": [], "overlays": [], "sounds": []}})
    tl.clips = clips
    for src, Kind, dest in ((d.get("overlays", []), Clip, tl.overlays), (d.get("sounds", []), Sound, tl.sounds)):
        for c in src:
            p = Path(c["path"])
            p = p if p.is_absolute() else base / p
            if p.exists():
                dest.append(Kind.from_json({**c, "path": str(p)}))
            else:
                missing.append(p.name)
    tl.reels = d.get("reels", {})
    tl.undo_stack.clear()
    tl.redo_stack.clear()
    tl.saved_state = tl.state()
    return missing


def bundle_project(tl, folder):
    """Copy the project and its media into one folder that can be zipped and sent to someone else."""
    folder = Path(folder)
    media = folder / "media"
    media.mkdir(parents=True, exist_ok=True)
    t = Exporter.copy(tl)
    names = {}
    for c in t.clips + t.overlays + t.sounds:
        if c.path not in names:
            target, i = media / Path(c.path).name, 1
            while target.exists() and not target.samefile(c.path):
                target, i = media / f"{Path(c.path).stem}_{i}{Path(c.path).suffix}", i + 1
            if not target.exists():
                shutil.copy2(c.path, target)
            names[c.path] = target
        c.path = str(names[c.path])
    save_project(t, folder / "project.bcproj", relative_to=folder)
    return folder / "project.bcproj"


def presets_for_camera(n):
    """A numbered CCTV feed: the mono security look with its own camera label."""
    p = next(x for x in presets.load_all() if x["name"] == "Security Cam B&W")
    steps = presets.build(p)
    for e in steps:
        if e.type == "text_stamp":
            e.v["text"] = e.v["text"].replace("CAM 03", f"CAM {n:02d}")
    return steps


class Session:
    """Editor state owned by the app: selection, playhead, playback clock, previews."""

    def __init__(self):
        self.tl, self.sel, self.t, self.playing = Timeline(), -1, 0.0, False
        self.over_sel, self.sound_sel, self.proxies, self.queue, self.queue_done = None, None, Proxies(), [], 0
        self.stems_note, self.reel, self.meter, self.lib_drag = None, "Main", [0.0, 0.0], None
        self.worker = audio.Worker()
        self.decoders = []
        self.thumbs, self.strips, self.waves = Thumbs(), {}, {}
        self.textures, self.seqs = {}, {}
        self.exporter, self.stream, self.sample = None, None, 0
        self.play_t0, self.zoom, self.scroll, self.drag = 0.0, 1.0, 0.0, None
        self.project_path, self.dirty_at = None, None
        self.recover = AUTOSAVE.exists()

    @property
    def clip(self):
        """The clip the sidebar edits: a selected overlay, or the selected main clip."""
        if self.over_sel is not None and self.over_sel < len(self.tl.overlays):
            return self.tl.overlays[self.over_sel]
        return self.tl.clips[self.sel] if 0 <= self.sel < len(self.tl.clips) else None

    @property
    def sound(self):
        return self.tl.sounds[self.sound_sel] if self.sound_sel is not None and self.sound_sel < len(self.tl.sounds) else None

    def add_sound(self, path, at=None, track=0):
        info = probe(path, need_video=False)
        s = Sound(path, info, self.t if at is None else at)
        s.track = track
        self.tl.sounds.append(s)
        self.track(s)
        self.sound_sel = len(self.tl.sounds) - 1
        return s

    def add_overlay(self, path, rect=(0.62, 0.05, 0.33, 0.33)):
        c = Clip(path, probe(path))
        c.at, c.rect = self.t, list(rect)
        self.tl.overlays.append(c)
        self.track(c)
        self.over_sel = len(self.tl.overlays) - 1
        return c

    def cut(self):
        """Cut whichever track has focus at the playhead. Returns False if the playhead isn't inside the selected item."""
        if self.sound:
            i = self.tl.split_item(self.tl.sounds, self.sound, self.t, lambda c: Sound.from_json(c.to_json(), c.info))
            self.sound_sel = self.sound_sel if i is None else i
            return i is not None
        if self.over_sel is not None and self.clip:
            i = self.tl.split_item(self.tl.overlays, self.clip, self.t, lambda c: Clip.from_json(c.to_json(), c.info))
            self.over_sel = self.over_sel if i is None else i
            return i is not None
        i = self.tl.split(self.t)
        self.sel = self.sel if i is None else i
        return i is not None

    def add_scare(self, entry=None):
        """Stinger, jolt and tape fault together at the playhead."""
        story.add_scare(self.tl, self.t)
        if entry:
            self.add_sound(entry["path"], self.t, 1).gain = 0.9

    def sync_take(self, clip, path):
        """Replace a clip's sound with a separately recorded take, lined up by matching the two waveforms."""
        offset, score = sound.find_offset(clip.sync_path or clip.path, path)
        clip.sync_path, clip.sync_offset = str(path), offset
        self.worker.pcm(clip.sync_path, audio.ORIGINAL)
        return offset, score

    def switch_reel(self, name):
        """Reels are timelines inside one project, so a feature can be cut in pieces."""
        tl = self.tl
        tl.reels[self.reel] = tl.state()
        state = tl.reels.get(name)
        if state:
            tl.load(json.loads(state), tl.infos())
        else:
            tl.load({"clips": []})
        tl.undo_stack.clear()
        tl.redo_stack.clear()
        tl.saved_state = tl.state()
        self.reel = name
        self.after_load()

    def nest_reel(self, name):
        """Render a reel to a master-quality file, then place it on this timeline as one clip."""
        state = self.tl.reels.get(name)
        if not state:
            return False
        folder = DATA / "captures" / "reels"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name.lower().replace(' ', '_')}.mov"
        fmt = "ProRes master 1080p 24"
        self.queue.append({"state": state, "fmt": fmt, "variant": "As edited", "path": str(path), "name": f"Reel {name}", "then": "place"})
        return True

    def set_loudness(self, target):
        """Measure the mix and set the master gain to hit a target, stopping short of clipping."""
        wav = audio.CACHE / "loudness_check.wav"
        self.tl.master = 0.0
        self.worker.wait(self.tl.audio_keys())
        write_wav(wav, self.tl, self.worker)
        lufs, peak = sound.measure_lufs(wav)
        wav.unlink(missing_ok=True)
        self.tl.master = round(min(target - lufs, -1.0 - peak), 2)
        return lufs, peak, self.tl.master

    def stop_preview(self):
        try:
            import sounddevice as sd
            sd.stop()
        except Exception as ex:
            print(f"[audio] {ex}")

    def preview_sound(self, path):
        try:
            import sounddevice as sd
            sd.play(sound.read_audio(path)[:SR * 30], SR)
        except Exception as ex:
            print(f"[audio] {ex}")

    def add_card(self, name, lines, seconds):
        when = None
        if self.clip is not None and self.clip.story:
            when = story.parse_when(self.clip.story)
        path = story.make_card(name, lines, seconds, when)
        c = Clip(path, probe(path))
        at = min(self.tl.index_at(self.t) + 1, len(self.tl.clips)) if self.tl.clips else 0
        self.tl.clips.insert(at, c)
        self.track(c)
        self.sel, self.over_sel = at, None
        return c

    def cctv(self, paths, mode, every=4.0, length=20.0):
        """Build a CCTV wall from up to four files: a quad split on the overlay track, or a switcher cutting between them on the main track."""
        infos = [probe(p) for p in paths[:4]]
        steps = lambda i: presets_for_camera(i)  # noqa: E731
        if mode == "Quad split":
            cells = [(0, 0), (0.5, 0), (0, 0.5), (0.5, 0.5)]
            span = min(length, min(i["duration"] for i in infos))
            for i, (p, info) in enumerate(zip(paths, infos)):
                c = Clip(p, info, 0.0, span)
                c.at, c.rect, c.opacity = self.t, [cells[i][0], cells[i][1], 0.5, 0.5], 1.0
                c.steps = steps(i + 1)
                self.tl.overlays.append(c)
                self.track(c)
            return
        t, i, at = 0.0, 0, len(self.tl.clips)
        span = min(i_["duration"] for i_ in infos)
        while t + 0.1 < min(length, span):
            n = i % len(paths)
            c = Clip(paths[n], infos[n], t, min(t + every, span))
            c.steps = steps(n + 1)
            self.tl.clips.insert(at, c)
            self.track(c)
            at, i, t = at + 1, i + 1, t + every

    def add_files(self, paths):
        """Returns error text for files that couldn't be read."""
        errors = []
        for p in paths:
            try:
                info = probe(p)
                c = Clip(p, info)
                self.tl.clips.append(c)
                self.track(c)
                self.sel = len(self.tl.clips) - 1
            except (ValueError, FileNotFoundError, OSError) as ex:
                errors.append(str(ex))
        self.tl.commit()
        return errors

    def track(self, c):
        """Queue thumbnails and audio for a clip's file."""
        if c.info.get("size") and c.path not in self.strips:
            self.strips[c.path] = None
            self.thumbs.add(c.path, c.info["duration"])
        if c.info["audio"]:
            self.worker.pcm(c.path, audio.ORIGINAL)

    def wave(self, path):
        if path not in self.waves:
            pcm = self.worker.pcm(path, audio.ORIGINAL)
            if pcm is None:
                return None
            self.waves[path] = audio.peaks(pcm)
        return self.waves[path]

    # ---- playback ----

    def playhead_source(self):
        """Source time in the selected clip, which is what keyframes are stored in."""
        for c, a, b in self.tl.layout() + [(o, o.at, o.at + o.length) for o in self.tl.overlays]:
            if c is self.clip:
                return c.start + min(max(self.t - a, 0.0), c.length)
        return None

    def seek(self, t):
        self.t = min(max(t, 0.0), self.tl.duration)
        self.sample, self.play_t0 = int(self.t * SR), time.perf_counter() - self.t

    def toggle_play(self):
        self.pause() if self.playing else self.play()

    def play(self):
        if not self.tl.clips:
            return
        if self.t >= self.tl.duration - 1e-3:
            self.seek(0)
        self.seek(self.t)
        self.playing = True
        try:
            import sounddevice as sd
            self.stream = sd.OutputStream(SR, channels=2, dtype="float32", callback=self.audio_out)
            self.stream.start()
        except Exception as ex:  # no sound device: video still plays against the wall clock
            print(f"[audio] {ex}")
            self.stream = None

    def pause(self):
        self.playing = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def audio_out(self, out, frames, info, status):
        try:
            out[:] = self.tl.mix(self.worker, self.sample / SR, frames)
        except Exception:  # timeline changed under us; a dropped buffer beats a dead stream
            out.fill(0)
        self.sample += frames
        self.meter = [float(np.abs(out[:, 0]).max()), float(np.abs(out[:, 1]).max())]

    def tick(self):
        """Advance the playhead from the audio clock (or the wall clock with no audio)."""
        if not self.playing:
            return
        if self.stream:
            self.t = max(0.0, self.sample / SR - self.stream.latency)
        else:
            self.t = time.perf_counter() - self.play_t0
        if self.t >= self.tl.duration:
            self.t = self.tl.duration
            self.pause()

    # ---- preview ----

    def render(self, g, bypass=False):
        """Render the frame at the playhead; returns the output texture or None."""
        self.tick()
        if not (self.tl.clips or self.tl.overlays):
            return None
        size, fps = self.tl.format()

        def frame_for(clip, src_t, slot):
            while slot >= len(self.decoders):
                self.decoders.append(Decoder())
            dec = self.decoders[slot]
            path = self.proxies.want(clip)
            info_size = decode_size(clip.info, Proxies.SIZE if path != clip.path else size)
            dec.seek(path, src_t, info_size, fps)
            frame = dec.frame
            if frame is None:
                return None
            h, w = frame.shape[:2]
            tex = self.textures.get((slot, w, h))
            if tex is None:
                tex = self.textures[(slot, w, h)] = g.ctx.texture((w, h), 3, alignment=1)
            if self.seqs.get(slot) != dec.seq:
                tex.write(frame.tobytes())
                self.seqs[slot] = dec.seq
            return tex

        return render_timeline(g, self.tl, self.t, frame_for, size, bypass)

    def next_job(self):
        """Start the next queued export, if there is one and nothing is running."""
        if self.exporter or not self.queue:
            return
        job = self.queue.pop(0)
        t = Timeline()
        d = json.loads(job["state"])
        t.load(d)
        t.fmt = job["fmt"]
        self.exporter = Exporter(t, self.worker, job.get("path"), variant=job["variant"])
        self.exporter.then = job.get("then")

    def job_done(self, ex):
        """After an export: nested reels drop themselves onto the current timeline."""
        if getattr(ex, "then", None) == "place" and not ex.error:
            c = Clip(ex.path, probe(ex.path))
            self.tl.clips.append(c)
            self.track(c)

    def enqueue(self, variant="As edited", path=None):
        self.queue.append({"state": self.tl.state(), "fmt": self.tl.fmt, "variant": variant, "path": path, "name": f"{variant}, {self.tl.fmt}"})

    # ---- persistence ----

    def autosave(self):
        """Called every frame: writes changes at most every 5 seconds, so a crash loses little."""
        if self.tl.commit():
            self.dirty_at = self.dirty_at or time.time()
        if self.dirty_at and time.time() - self.dirty_at > 5:
            save_project(self.tl, AUTOSAVE)
            self.dirty_at = None

    def clean_exit(self):
        AUTOSAVE.unlink(missing_ok=True)

    def recover_autosave(self):
        missing = load_project(self.tl, AUTOSAVE)
        self.after_load()
        self.recover = False
        return missing

    def after_load(self):
        self.sel = 0 if self.tl.clips else -1
        for c in self.tl.clips + self.tl.overlays + self.tl.sounds:
            self.track(c)
        self.over_sel, self.sound_sel = None, None
        self.seek(0)

    def close(self):
        self.pause()
        for d in self.decoders:
            d.stop()
