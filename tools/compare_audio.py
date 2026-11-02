"""Measure real tape audio and processed audio the same way.

  python tools/compare_audio.py FILE [FILE...]       measure recordings
  python tools/compare_audio.py --presets SPEECH     run clean speech through every preset and measure

gap_dB is how far the noise in pauses sits below speech: the number that decides whether dialogue can be heard.
"""
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from badcamera import audio  # noqa: E402
from badcamera.output import SR, ffmpeg  # noqa: E402
import subprocess  # noqa: E402


def load(path):
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, "i2").astype("f8") / 32768


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-7))


def measure(x):
    win = SR // 20  # 50 ms
    n = len(x) // win
    rms = np.sqrt((x[:n * win].reshape(n, win) ** 2).mean(axis=1))
    level = db(rms)
    loud, quiet = np.percentile(level, 95), np.percentile(level, 7)
    k = SR // 2
    f = np.fft.rfftfreq(k, 1 / SR)
    frames = [x[i:i + k] * np.hanning(k) for i in range(0, len(x) - k, k // 2)]
    p = np.mean([np.abs(np.fft.rfft(fr)) ** 2 for fr in frames], axis=0)
    ref = p[(f > 300) & (f < 1000)].mean()
    edge = {}
    for drop in (10, 30):
        above = f[(p > ref * 10 ** (-drop / 10)) & (f > 1000)]
        smooth = np.convolve(p, np.ones(201) / 201, "same")
        above = f[(smooth > ref * 10 ** (-drop / 10)) & (f > 200)]
        edge[drop] = float(above.max()) if len(above) else 0.0
    low = f[(np.convolve(p, np.ones(9) / 9, "same") > ref * 0.1) & (f < 300)]
    hum = max(10 * np.log10(p[(f > h - 3) & (f < h + 3)].max() / np.median(p[(f > h - 30) & (f < h + 30)])) for h in (60, 120, 180))
    return {"loud_dB": float(loud), "quiet_dB": float(quiet), "gap_dB": float(loud - quiet), "low_Hz": float(low.min()) if len(low) else 0.0, "hi10_Hz": edge[10], "hi30_Hz": edge[30], "hum_dB": float(hum)}


def speech_kept(dry, wet):
    """Does the speech's rhythm survive? Compares the loudness contour during speech only (pauses are allowed to hold noise)."""
    n = min(len(dry), len(wet))
    e = lambda s: db(np.sqrt(np.convolve(s[:n] ** 2, np.ones(2400) / 2400, "same"))[::1200])  # noqa: E731
    a, b = e(dry), e(wet)
    talk = a > np.percentile(a, 95) - 25
    return float(np.corrcoef(a[talk], b[talk])[0, 1])


def show(name, m, extra=""):
    print(f"{name:20}" + "".join(f"{m[k]:9.1f}" for k in ("loud_dB", "quiet_dB", "gap_dB", "low_Hz", "hi10_Hz", "hi30_Hz", "hum_dB")) + extra)


def main():
    print(f"{'source':20}{'loud':>9}{'quiet':>9}{'gap':>9}{'lowHz':>9}{'hi-10':>9}{'hi-30':>9}{'hum':>9}")
    if sys.argv[1] == "--presets":
        dry = load(sys.argv[2])
        show("clean speech", measure(dry))
        with tempfile.TemporaryDirectory() as t:
            for name in audio.NAMES[1:]:
                out = Path(t) / "o.s16"
                audio.render_to(sys.argv[2], name, out)
                wet = np.fromfile(out, "i2").reshape(-1, 2).mean(axis=1) / 32768
                corr = speech_kept(dry, wet)
                show(name, measure(wet), f"   speech-kept {corr:.2f}")
        return
    for p in sys.argv[1:]:
        show(Path(p).parent.name, measure(load(p)))


if __name__ == "__main__":
    main()
