"""Measure every audio preset with test signals and compare to the hardware figures in audio.PRESETS.

Run from the project root: python -m tests.test_audio
"""
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from badcamera import audio
from badcamera.output import SR

DUR = 8
# name: (low -3 dB Hz, high -3 dB Hz, wow/flutter %) with allowed ranges; None = don't check
TARGET = {
    "VHS linear SP": ((70, 140), (7000, 11500), (0.1, 0.35)),
    "VHS linear EP": ((70, 140), (3500, 5800), (0.2, 0.6)),
    "VHS Hi-Fi": ((10, 40), (15000, 24000), None),
    "Camcorder mic": ((90, 220), (5000, 9000), None),
    "Old landline": ((250, 420), (2900, 3700), None),
    "2000s cell phone": ((230, 450), (2700, 3800), None),
    "Cassette": ((25, 70), (8000, 14000), (0.1, 0.4)),
    "AM radio": ((90, 200), (3500, 5500), None),
    "CCTV mic": ((250, 500), (2200, 3400), None),
}
# How far noise in pauses must sit below speech, in dB. Real speech tapes measured 20-36 dB; dialogue has to stay on top.
GAP = {"VHS linear SP": (30, 42), "VHS linear EP": (28, 40), "VHS Hi-Fi": (50, 80), "Camcorder mic": (28, 40), "Old landline": (30, 45),
       "2000s cell phone": (35, 60), "Cassette": (32, 46), "AM radio": (26, 38), "CCTV mic": (26, 40)}


def write(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("i2").tobytes())


def run(src, preset, tmp):
    out = Path(tmp) / "out.s16"
    audio.render_to(src, preset, out)
    return np.fromfile(out, "i2").reshape(-1, 2)[:, 0].astype("f8") / 32768


def band(sig_out, sig_in):
    """-3 dB band edges of out/in, on 1/3-octave power so codec and compressor ripple doesn't matter."""
    n = min(len(sig_in), len(sig_out))
    f = np.fft.rfftfreq(n, 1 / SR)
    po, pi = np.abs(np.fft.rfft(sig_out[:n] * np.hanning(n))) ** 2, np.abs(np.fft.rfft(sig_in[:n] * np.hanning(n))) ** 2
    centers = 20 * 2 ** (np.arange(0, 30) / 3)
    centers = centers[centers < SR / 2 / 1.13]
    g = np.array([po[(f > c / 1.12) & (f < c * 1.12)].sum() / max(pi[(f > c / 1.12) & (f < c * 1.12)].sum(), 1e-12) for c in centers])
    g = 10 * np.log10(g + 1e-12)
    ref = np.max(g)
    hit = centers[g > ref - 3]
    return float(hit[0]), float(hit[-1])


def wow(sig):
    """Peak-ish speed variation (%) of a 3.15 kHz tone, the IEC test frequency, from its instantaneous frequency."""
    n = len(sig) // 8
    sig = sig[n:-n]
    spec = np.fft.fft(sig)
    f = np.fft.fftfreq(len(sig), 1 / SR)
    spec[(f < 2800) | (f > 3500)] = 0  # analytic band around the tone
    z = np.fft.ifft(spec * 2)
    inst = np.diff(np.unwrap(np.angle(z))) * SR / (2 * np.pi)
    inst = inst[SR // 10:-SR // 10]
    kernel = np.ones(SR // 400) / (SR // 400)  # drop modulation above the wow/flutter band
    smooth = np.convolve(inst, kernel, "valid")
    return float(100 * np.percentile(np.abs(smooth - np.median(smooth)), 95) / np.median(smooth))


def speech_like(level_db, seed=2):
    """Shaped noise switched on and off like syllables and pauses, at a chosen level. Needs no bundled recording."""
    rng = np.random.default_rng(seed)
    n = DUR * SR
    x = np.cumsum(rng.standard_normal(n)) * 0.02  # dark, speech-like spectrum
    x -= np.convolve(x, np.ones(480) / 480, "same")
    t = np.arange(n) / SR
    env = ((t % 1.0) < 0.55) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t) ** 2)
    x = x * env
    loud = np.sqrt((x[env > 0] ** 2).mean())
    return x / loud * 10 ** (level_db / 20)


def gap_and_level(x):
    w = SR // 20
    k = len(x) // w
    lv = 20 * np.log10(np.sqrt((x[:k * w].reshape(k, w) ** 2).mean(axis=1)) + 1e-7)
    return float(np.percentile(lv, 90) - np.percentile(lv, 10)), float(np.percentile(lv, 90))


def main():
    rng = np.random.default_rng(1)
    t = np.arange(DUR * SR) / SR
    white, tone = 0.25 * rng.standard_normal(len(t)), 0.3 * np.sin(2 * np.pi * 3150 * t)
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        files = {}
        for name, sig in (("white", white), ("tone", tone), ("speech", speech_like(-22)), ("quiet", speech_like(-40))):
            files[name] = Path(tmp) / f"{name}.wav"
            write(files[name], sig)
        print(f"{'preset':20}{'low Hz':>8}{'high Hz':>9}{'w&f %':>8}{'gap dB':>9}{'quiet gap':>11}{'level':>8}")
        for name, (lo_t, hi_t, wf_t) in TARGET.items():
            lo, hi = band(run(files["white"], name, tmp), white)
            wf = wow(run(files["tone"], name, tmp))
            gap, level = gap_and_level(run(files["speech"], name, tmp))
            quiet, q_level = gap_and_level(run(files["quiet"], name, tmp))
            print(f"{name:20}{lo:8.0f}{hi:9.0f}{wf:8.3f}{gap:9.1f}{quiet:11.1f}{level + 22:+8.1f}")
            checks = [("low", lo, lo_t), ("high", hi, hi_t), ("w&f", wf, wf_t), ("gap", gap, GAP[name]), ("quiet gap", quiet, GAP[name]),
                      ("level change", level + 22, (-5, 4)), ("quiet level change", q_level + 40, (-5, 4))]
            failures += [f"{name} {k}={v:.2f} outside {r}" for k, v, r in checks if r and not r[0] <= v <= r[1]]
        # The Tape noise slider: 0 removes it, 200% adds about 6 dB.
        def floor(n):
            out = Path(tmp) / "o.s16"
            audio.render_to(files["speech"], "VHS linear SP", out, noise=n)
            return gap_and_level(np.fromfile(out, "i2").reshape(-1, 2)[:, 0].astype("f8") / 32768)[0]
        off, normal, double = floor(0.0), floor(1.0), floor(2.0)
        print(f"tape noise slider gap: 0% {off:.1f}, 100% {normal:.1f}, 200% {double:.1f}")
        if not (off > normal + 15 and 3 < normal - double < 9):
            failures.append("tape noise slider doesn't scale")
    print("\n".join(failures) or "all audio presets within target")
    assert not failures


if __name__ == "__main__":
    main()
