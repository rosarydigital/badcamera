"""Hardware-style audio: each preset is an ffmpeg filter graph, rendered once to a cache file so preview and export match."""
import hashlib
import os
import queue
import subprocess
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .output import SR, ffmpeg, has_encoder

CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "badcamera" / "audio"
VERSION = 4  # bump when a preset's sound changes so cached renders are redone
ORIGINAL = "Original"
MONO = "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1"
NOMINAL = -20.0  # record level, dBFS. Real gear rides its input to about here, so noise stays a fixed distance below the program.
DENOISE = {"Off": 0, "Light": 14, "Strong": 28}  # dB of reduction, to clean a take before the hardware degrades it
NOISE_STEPS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)  # tape noise amounts, kept to steps so renders can be cached


def db(x):
    return 10 ** (x / 20)


def tape_noise(level, seed=1, tone=5000):
    """Measured off real tapes: noise is dark, falling 9-27 dB by 8 kHz. Pink through a soft lowpass matches it; white hiss doesn't."""
    return f"anoisesrc=color=pink:amplitude=1:sample_rate={SR}:seed={seed},lowpass=f={tone}:poles=1,volume={level:.1f}dB"


def hum(freq, level):
    return f"aevalsrc=(sin(2*PI*{freq}*t)+0.5*sin(2*PI*{freq * 3}*t)+0.25*sin(2*PI*{freq * 5}*t)):s={SR},volume={level:.1f}dB"


def tape(hp, lp, wow, flutter, noise_level, comp=True, mono=True, tone=5000):
    """Tape replay: band-limited record path, speed drift (wow/flutter), then noise on replay, shaped by the same EQ."""
    parts = [MONO] if mono else []
    edge = lp * 1.3  # two 2-pole stages (here and in the replay EQ) land the -3 dB point near lp
    parts += [f"highpass=f={hp}", f"lowpass=f={edge:.0f}:poles=2"]
    if comp:
        parts.append("acompressor=threshold=-18dB:ratio=2.5:attack=8:release=250")
    parts += [f"vibrato=f=0.7:d={wow:.3f}", f"vibrato=f=9.3:d={flutter:.3f}", "asoftclip=type=tanh"]
    return ",".join(parts), [tape_noise(noise_level, tone=tone)], f"lowpass=f={edge:.0f}:poles=2,highpass=f={hp}"


@dataclass
class Preset:
    pre: str  # filters on the program, at record level
    extras: list = None  # noise sources mixed in after `pre`, levels relative to full scale
    post: str = ""  # filters after the mix
    codec: tuple = None  # (encoder, container) for a real codec round trip at 8 kHz mono
    fallback: str = ""  # used when this ffmpeg lacks the encoder
    makeup: float = 0.0  # dB: band-limiting removes energy, so bring it back to match the original's loudness


PRESETS = {
    ORIGINAL: None,
    "VHS linear SP": Preset(*tape(100, 10000, 0.12, 0.006, -40), makeup=4),
    "VHS linear EP": Preset(*tape(100, 5000, 0.2, 0.012, -36), makeup=4),
    "VHS Hi-Fi": Preset("highpass=f=20", [tape_noise(-66), f"aevalsrc=lt(mod(t*59.94\\,1)\\,0.0006):s={SR},volume=-62dB"], ""),
    "Camcorder mic": Preset(  # noise goes in before the AGC, so it comes up gently in pauses as on the real thing
        f"{MONO},highpass=f=130,lowpass=f=8000:poles=2,lowpass=f=11000:poles=2",
        [tape_noise(-46, tone=4000), f"sine=f=1180:r={SR},volume=-68dB", f"anoisesrc=color=brown:amplitude=1:sample_rate={SR}:seed=3,lowpass=f=70,tremolo=f=1.3:d=0.8,volume=-58dB"],
        "acompressor=threshold=-26dB:ratio=3:attack=6:release=500:makeup=2dB,asoftclip=type=tanh", makeup=7),
    "Old landline": Preset(
        f"{MONO},highpass=f=240:poles=2,lowpass=f=4300:poles=2,acompressor=threshold=-20dB:ratio=3:makeup=2dB,asoftclip=type=tanh",
        [tape_noise(-43, tone=3000)], "highpass=f=240:poles=2,lowpass=f=4300:poles=2", codec=("pcm_mulaw", "mulaw"), makeup=7),
    "2000s cell phone": Preset(
        f"{MONO},highpass=f=240:poles=2,lowpass=f=4300:poles=2,acompressor=threshold=-22dB:ratio=3:makeup=2dB", [tape_noise(-60, tone=3000)],
        "highpass=f=240:poles=2,lowpass=f=4300:poles=2", codec=("libgsm", "gsm"),
        fallback="acrusher=bits=8:mode=log:aa=1:samples=1", makeup=8),
    "Cassette": Preset(*tape(40, 12000, 0.15, 0.008, -44, comp=False, mono=False, tone=7000), makeup=3),
    "AM radio": Preset(
        f"{MONO},highpass=f=120:poles=2,lowpass=f=6200:poles=2,acompressor=threshold=-24dB:ratio=4:attack=2:release=80:makeup=3dB,asoftclip=type=tanh",
        [tape_noise(-40, tone=4500), hum(60, -60)], "lowpass=f=6200:poles=2", makeup=6),
    "CCTV mic": Preset(
        f"{MONO},highpass=f=300:poles=2,lowpass=f=3700:poles=2", [tape_noise(-42, tone=3500), hum(60, -52)],
        "highpass=f=240:poles=2,lowpass=f=3700:poles=2,acompressor=threshold=-24dB:ratio=3:attack=4:release=300:makeup=2dB,asoftclip=type=tanh", makeup=7),
}
NAMES = list(PRESETS)


def spectral_clean(x, reduction_db):
    """Spectral subtraction: learn the noise's fingerprint from the quietest moments, then remove that much from every frequency.
    Gain is smoothed over time so the result doesn't warble, and floored so it never sounds gated."""
    n, hop = 2048, 512
    if len(x) < n * 4:
        return x
    win = np.hanning(n)
    pad = np.concatenate([np.zeros(n), x, np.zeros(n)])
    frames = (len(pad) - n) // hop
    energy = np.array([np.sqrt((pad[i * hop:i * hop + n] ** 2).mean()) for i in range(0, frames, 8)])
    quiet = np.argsort(energy)[:max(8, len(energy) // 8)] * 8
    noise = np.mean([np.abs(np.fft.rfft(pad[i * hop:i * hop + n] * win)) for i in quiet], axis=0)
    floor = 10 ** (-reduction_db / 20)
    out, norm = np.zeros(len(pad)), np.zeros(len(pad))
    last = np.ones(n // 2 + 1)
    for start in range(0, frames, 256):  # in batches, so an hour of audio doesn't need an hour's worth of memory at once
        idx = np.arange(start, min(start + 256, frames))
        block = np.stack([pad[i * hop:i * hop + n] for i in idx]) * win
        spec = np.fft.rfft(block, axis=1)
        mag = np.abs(spec) + 1e-12
        gain = np.maximum(1 - (1.2 + reduction_db / 20) * noise / mag, floor)  # noise peaks go above its average, so subtract a bit extra
        for k in range(len(gain)):
            last = gain[k] = np.maximum(gain[k], last * 0.7 + floor * 0.3)  # releases gently rather than chattering
        back = np.fft.irfft(spec * gain, n=n, axis=1) * win
        for k, i in enumerate(idx):
            out[i * hop:i * hop + n] += back[k]
            norm[i * hop:i * hop + n] += win ** 2
    return (out / np.maximum(norm, 1e-6))[n:n + len(x)]


def denoised(source, amount):
    """A cleaned copy of the file's audio, as a cached WAV. Returns the original path when noise reduction is off."""
    if not DENOISE[amount]:
        return source
    st = Path(source).stat()
    key = hashlib.sha1(f"{VERSION}|{Path(source).resolve()}|{st.st_mtime_ns}|{amount}".encode()).hexdigest()
    out = CACHE / f"clean_{key}.wav"
    if out.exists():
        return out
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(source), "-vn", "-ac", "2", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, "i2").reshape(-1, 2).astype("f8") / 32768
    clean = np.stack([spectral_clean(x[:, c], DENOISE[amount]) for c in (0, 1)], axis=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(f"{out.name}.{os.getpid()}.part")
    with wave.open(str(part), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(clean, -1, 1) * 32767).astype("i2").tobytes())
    part.replace(out)
    return out


def spaced(source, space, denoise):
    """The source played in a room, as a cached WAV. A room happens in front of the microphone, so it goes before the hardware."""
    if space == "None":
        return source
    from . import sound
    st = Path(source).stat()
    out = CACHE / f"room_{hashlib.sha1(f'{VERSION}|{Path(source).resolve()}|{st.st_mtime_ns}|{space}|{denoise}'.encode()).hexdigest()}.wav"
    if not out.exists():
        part = out.with_name(f"{out.name}.{os.getpid()}.part")
        sound.write_wav(part, sound.apply_room(sound.read_audio(source), space))
        part.replace(out)
    return out


def speech_level(source):
    """Loud-moment level of a file in dBFS, what a real recorder's level control would ride. Clamped so near-silence can't blast the noise."""
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, "i2").astype("f8") / 32768
    n = len(x) // 800
    if not n:
        return NOMINAL
    rms = np.sqrt((x[:n * 800].reshape(n, 800) ** 2).mean(axis=1))
    return float(np.clip(20 * np.log10(max(np.percentile(rms, 90), 1e-6)), -50.0, -3.0))


def graph(p, codec_ok, gain, noise):
    """filter_complex for a preset, ending in [out]. `gain` brings the program to record level; `noise` scales everything but the program."""
    labels, g = [], [f"[0:a]aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=stereo,volume={gain:.2f}dB,{p.pre}[s]"]
    if noise > 0:
        trim = 20 * np.log10(noise)
        for i, e in enumerate(p.extras or []):
            g.append(f"{e},volume={trim:.2f}dB,aformat=channel_layouts=stereo[x{i}]")
            labels.append(f"[x{i}]")
    mix = f"[s]{''.join(labels)}amix=inputs={len(labels) + 1}:duration=first:normalize=0" if labels else "[s]anull"
    tail = p.post if codec_ok or not p.fallback else ",".join(x for x in (p.post, p.fallback) if x)
    g.append(f"{mix}{',' + tail if tail else ''}[out]")
    return ";".join(g)


def render_to(source, preset, out, fmt=("-f", "s16le", "-ac", "2", "-ar", str(SR)), noise=1.0, denoise="Off", space="None"):
    """Run `source` through `preset` (None = plain decode) and write the audio to `out`.
    The program goes in at record level, noise is added there, and the original loudness comes back at the end,
    so noise stays the same distance below your audio on loud and quiet clips alike."""
    source = spaced(denoised(source, denoise), space, denoise)
    ff, src = [ffmpeg(), "-loglevel", "error", "-y"], ["-i", str(source)]
    p = PRESETS.get(preset)
    if p is None:
        subprocess.run([*ff, *src, "-vn", *fmt, str(out)], check=True)
        return
    gain = NOMINAL - speech_level(source)
    restore = f"volume={p.makeup - gain:.2f}dB"
    codec_ok = p.codec is None or has_encoder(p.codec[0])
    g = graph(p, codec_ok, gain, noise)
    if p.codec and codec_ok:
        enc, container = p.codec
        a = subprocess.Popen([*ff, *src, "-filter_complex", g, "-map", "[out]", "-ac", "1", "-ar", "8000", "-c:a", enc, "-f", container, "-"],
                             stdout=subprocess.PIPE)
        b = subprocess.Popen([*ff, "-f", container, "-ar", "8000", "-ac", "1", "-i", "-", "-af", f"aresample={SR},{restore}", *fmt, str(out)], stdin=a.stdout)
        a.stdout.close()
        if b.wait() or a.wait():
            raise RuntimeError(f"audio preset {preset} failed")
        return
    subprocess.run([*ff, *src, "-filter_complex", g.replace("[out]", f",{restore}[out]"), "-map", "[out]", *fmt, str(out)], check=True)


def process_file(path, preset):
    """One-shot render for a finished recording. Returns the new WAV's path."""
    out = Path(path).with_suffix(".wet.wav")
    render_to(path, preset, out, ("-ar", str(SR)))
    return out


def cache_path(path, preset, noise=1.0, denoise="Off", space="None"):
    st = Path(path).stat()
    key = f"{VERSION}|{Path(path).resolve()}|{st.st_mtime_ns}|{st.st_size}|{preset}|{noise}|{denoise}|{space}"
    return CACHE / f"{hashlib.sha1(key.encode()).hexdigest()}.s16"


class Worker(threading.Thread):
    """Renders cached audio in the background; memmaps finished files. Until then `pcm` returns None and playback uses what it has."""

    def __init__(self):
        super().__init__(daemon=True)
        self.q, self.maps, self.pending, self.errors = queue.Queue(), {}, set(), {}
        self.start()

    def run(self):
        while True:
            key = self.q.get()
            path, preset, noise, denoise, space = key
            out = cache_path(*key)
            try:
                if not out.exists():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    part = out.with_name(f"{out.name}.{os.getpid()}.part")
                    render_to(path, preset, part, noise=noise, denoise=denoise, space=space)
                    part.replace(out)
            except Exception as ex:
                self.errors[key] = str(ex)
            self.pending.discard(key)

    def pcm(self, path, preset, noise=1.0, denoise="Off", space="None"):
        """Stereo int16 frames for this file and preset, or None while rendering (a render is queued automatically)."""
        key = (path, preset, noise, denoise, space)
        if key in self.maps:
            return self.maps[key]
        out = cache_path(*key)
        if out.exists():
            size = out.stat().st_size
            self.maps[key] = np.memmap(out, np.int16, "r").reshape(-1, 2) if size >= 4 else np.zeros((0, 2), np.int16)
            return self.maps[key]
        if key not in self.pending and key not in self.errors:
            self.pending.add(key)
            self.q.put(key)
        return None

    def wait(self, keys):
        """Block until these (path, preset) renders exist. Used by export."""
        for key in keys:
            self.pcm(*key)
        while any(k in self.pending for k in keys):
            threading.Event().wait(0.05)


def peaks(pcm, rate=50):
    """Peak per 1/rate seconds, for drawing the waveform."""
    step = SR // rate
    n = len(pcm) // step
    if not n:
        return np.zeros(0, "f4")
    return np.abs(pcm[:n * step, 0]).reshape(n, step).max(axis=1).astype("f4") / 32768
