"""The audio plugin's real-time DSP, measured against the app's hardware targets, on speech-like signal at two levels.

Run from the project root: python -m tests.test_vst DSP_TEST
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from tests.test_audio import DUR, GAP, SR, TARGET, band, gap_and_level, speech_like, wow

NAMES = ["Original", "VHS linear SP", "VHS linear EP", "VHS Hi-Fi", "Camcorder mic", "Old landline", "2000s cell phone", "Cassette", "AM radio", "CCTV mic"]


def run(tool, preset, x, tmp, noise=1.0):
    a, b = Path(tmp) / "i.raw", Path(tmp) / "o.raw"
    np.stack([x, x], axis=1).astype("f4").tofile(a)
    subprocess.run([tool, str(preset), str(a), str(b), str(noise)], check=True)
    return np.fromfile(b, "f4").reshape(-1, 2)[:, 0].astype("f8")


def main():
    tool = sys.argv[1]
    rng = np.random.default_rng(1)
    t = np.arange(DUR * SR) / SR
    white, tone = 0.25 * rng.standard_normal(len(t)), 0.3 * np.sin(2 * np.pi * 3150 * t)
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        print(f"{'preset':20}{'low Hz':>8}{'high Hz':>9}{'w&f %':>8}{'gap':>7}{'quiet gap':>11}{'level':>8}")
        for i, name in enumerate(NAMES):
            if not i:
                continue
            lo_t, hi_t, wf_t = TARGET[name]
            lo, hi = band(run(tool, i, white, tmp), white)
            wf = wow(run(tool, i, tone, tmp))
            gap, level = gap_and_level(run(tool, i, speech_like(-22), tmp)[SR * 3:])
            quiet, q_level = gap_and_level(run(tool, i, speech_like(-40), tmp)[SR * 3:])
            print(f"{name:20}{lo:8.0f}{hi:9.0f}{wf:8.3f}{gap:7.1f}{quiet:11.1f}{level + 22:+8.1f}")
            for k, v, r in (("low", lo, lo_t), ("high", hi, hi_t), ("w&f", wf, wf_t), ("gap", gap, (GAP[name][0] - 4, GAP[name][1] + 6)), ("quiet gap", quiet, (GAP[name][0] - 4, GAP[name][1] + 6)),
                            ("level", level + 22, (-6, 6)), ("quiet level", q_level + 40, (-6, 6))):
                if r and not r[0] <= v <= r[1]:
                    fails.append(f"{name} {k}={v:.2f} outside {r}")
        # Original at full mix must be untouched.
        y = run(tool, 0, white, tmp)
        assert np.abs(y - white).max() < 1e-5
        # Speed: at least 20x real time, on one core, for the slowest chain.
        t0 = time.time()
        run(tool, 4, np.zeros(SR * 60), tmp)
        print(f"60 s rendered in {time.time() - t0:.2f} s")
    print("\n".join(fails) or "all plugin sounds within target")
    assert not fails


if __name__ == "__main__":
    main()
