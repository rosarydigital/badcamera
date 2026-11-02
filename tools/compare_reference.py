"""Measure real tape footage and simulated footage the same way, so a look can be tuned against numbers rather than memory.

  python tools/compare_reference.py metrics FILE [FILE...]      print metrics for videos or images
  python tools/compare_reference.py sheet OUT.png A B [C...]    side-by-side frames, with a 2x crop of each

Reference footage is kept outside the repo; it is never committed or bundled.
"""
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

KEYS = ["luma_tvl", "chroma_tvl", "chroma_ratio", "noise", "streak_px", "jitter_px", "black", "white", "sat", "temporal"]


def read_frames(path, n=24):
    """Frames as BGR uint8, decoded with ffmpeg, without deinterlacing."""
    path = str(path)
    if path.lower().endswith((".png", ".jpg", ".jpeg")):
        return [cv2.imread(path)]
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                          capture_output=True, text=True).stdout.strip().split(",")
    w, h = int(info[0]), int(info[1])
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
    k = len(raw) // (w * h * 3)
    return list(np.frombuffer(raw[:k * w * h * 3], np.uint8).reshape(k, h, w, 3))


def active_area(frames):
    """Crop every frame the same way: drop black side bars and the bottom of the frame (head-switching and overscan)."""
    h, w = frames[0].shape[:2]
    col = np.mean(frames, axis=(0, 1, 3))
    on = np.flatnonzero(col > 12)
    x0, x1 = (on[0], on[-1] + 1) if len(on) > w / 2 else (0, w)
    return [f[int(h * 0.04):int(h * 0.94), x0 + 4:x1 - 4] for f in frames]


def cutoff_tvl(channel, picture_h, keep=0.97):
    """Resolution in TV lines per picture height: where horizontal detail falls into the noise floor.
    Uses a power-spectrum knee, so it reads the same on any picture content."""
    x = channel.astype("f8")
    x = x - x.mean(axis=1, keepdims=True)
    win = np.hanning(x.shape[1])
    p = (np.abs(np.fft.rfft(x * win, axis=1)) ** 2).mean(axis=0)[1:]
    f = np.arange(1, len(p) + 1) / x.shape[1]  # cycles per pixel
    floor = np.median(p[-len(p) // 8:])
    p = np.maximum(p - floor, 1e-9)
    weighted = np.cumsum(p * f)  # weighting by frequency makes the fine detail count
    cycles_per_px = f[np.searchsorted(weighted, keep * weighted[-1])]
    aspect_w = picture_h * 4 / 3
    return float(2 * cycles_per_px * x.shape[1] * picture_h / aspect_w)


def flat_mask(y):
    """Pixels away from edges and clipping, where any variation is noise rather than picture."""
    blur = cv2.GaussianBlur(y, (0, 0), 3)
    edges = np.abs(cv2.Laplacian(blur, cv2.CV_32F))
    return (edges < np.percentile(edges, 45)) & (blur > 25) & (blur < 225)


def noise_stats(frames):
    y0 = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype("f4") for f in frames]
    if len(y0) > 1:  # frame differences remove the picture entirely on static shots
        d = [(a - b) / np.sqrt(2) for a, b in zip(y0[1:], y0[:-1])]
    else:
        d = [y0[0] - cv2.GaussianBlur(y0[0], (0, 0), 2)]
    # keep the quietest (least motion) quarter of each difference, in tiles
    vals, acf = [], []
    for x, y in zip(d, y0):
        m = flat_mask(y)
        h, w = x.shape
        for ty in range(0, h - 32, 32):
            for tx in range(0, w - 32, 32):
                if m[ty:ty + 32, tx:tx + 32].mean() > 0.9:
                    t = x[ty:ty + 32, tx:tx + 32]
                    vals.append(t.std())
                    t = t - t.mean()
                    r = [(t[:, :-k or None] * t[:, k:]).mean() / max((t * t).mean(), 1e-6) for k in range(0, 9)]
                    acf.append(r)
    if not vals:
        return float("nan"), float("nan")
    vals = np.array(vals)
    quiet = vals <= np.percentile(vals, 30)
    r = np.array(acf)[quiet].mean(axis=0)
    below = np.flatnonzero(r < 0.5)
    return float(np.median(vals[quiet])), float(below[0] if len(below) else 9)


def jitter(frames):
    """Line-to-line horizontal wobble: how far each scanline is displaced from its neighbours on vertical detail."""
    out = []
    for f in frames[:8]:
        y = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype("f4")
        y = y[::2]  # one field, so interlace combing doesn't read as jitter
        grad = cv2.Sobel(y, cv2.CV_32F, 1, 0, ksize=3)
        h, w = y.shape
        shifts = []
        for line in range(4, h - 4, 3):
            a, b = grad[line], grad[line - 2:line + 3].mean(axis=0)
            if a.std() < 3:
                continue
            c = np.correlate(a - a.mean(), b - b.mean(), "full")
            mid = len(c) // 2
            window = c[mid - 8:mid + 9]
            k = int(window.argmax())
            if 0 < k < 16:
                d = (window[k - 1] - window[k + 1]) / (2 * (window[k - 1] - 2 * window[k] + window[k + 1]) - 1e-9)
                shifts.append(k - 8 + d)
        if shifts:
            out.append(np.std(shifts))
    return float(np.median(out)) if out else float("nan")


def metrics(path):
    frames = active_area(read_frames(path))
    f = frames[len(frames) // 2]
    h = f.shape[0]
    ycc = cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)
    y, cr, cb = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    luma = np.median([cutoff_tvl(cv2.cvtColor(x, cv2.COLOR_BGR2GRAY), h) for x in frames[::4]])
    chroma = np.median([cutoff_tvl(cv2.cvtColor(x, cv2.COLOR_BGR2YCrCb)[..., 1], h) for x in frames[::4]])
    noise, streak = noise_stats(frames)
    sat = float(np.hypot(cr.astype("f4") - 128, cb.astype("f4") - 128).mean())
    t = float(np.mean([np.abs(a.astype("f4") - b.astype("f4")).mean() for a, b in zip(frames[1:], frames[:-1])])) if len(frames) > 1 else 0.0
    return {"luma_tvl": float(luma), "chroma_tvl": float(chroma), "chroma_ratio": float(chroma / max(luma, 1)), "noise": noise, "streak_px": streak,
            "jitter_px": jitter(frames), "black": float(np.percentile(y, 1)), "white": float(np.percentile(y, 99)), "sat": sat, "temporal": t}


def bar_edges(path):
    """On colour bars: 10-90% rise of luma and chroma at each bar edge (percent of picture width), overshoot, and chroma lag behind luma."""
    f = read_frames(path)[0]
    h, w = f.shape[:2]
    band = cv2.cvtColor(f[int(h * 0.2):int(h * 0.55)], cv2.COLOR_BGR2YCrCb).astype("f4").mean(axis=0)
    y, c = band[:, 0], np.hypot(band[:, 1] - 128, band[:, 2] - 128)

    def edges(sig, min_step):
        rises, centers = [], []
        smooth = cv2.GaussianBlur(sig.reshape(1, -1), (0, 0), 1.5).ravel()
        d = np.abs(np.diff(smooth))
        i = int(w * 0.14)
        while i < w * 0.97:
            if d[i] > d[max(i - 12, 0):i + 12].max() - 1e-6 and d[i] > 0.4:
                a, b = sig[max(i - w // 28, 0):i - w // 45].mean(), sig[i + w // 45:i + w // 28].mean()
                if abs(b - a) > min_step:
                    seg = (sig[i - w // 30:i + w // 30] - a) / (b - a)
                    lo, hi = np.flatnonzero(seg > 0.1), np.flatnonzero(seg > 0.9)
                    if len(lo) and len(hi) and hi[0] > lo[0]:
                        rises.append(100 * (hi[0] - lo[0]) / w)
                        centers.append(i + (lo[0] - w // 30))
                        i += w // 25
                        continue
            i += 1
        return rises, centers
    ly, _ = edges(y, 30)
    lc, _ = edges(c, 20)
    return {"luma_rise%": float(np.median(ly)) if ly else float("nan"), "chroma_rise%": float(np.median(lc)) if lc else float("nan"),
            "white": float(np.percentile(y, 99)), "yellow_sat": float(c[int(w * 0.33)]), "edges": len(ly)}


def sheet(out, paths):
    rows = []
    for p in paths:
        frames = read_frames(p)
        f = frames[len(frames) // 2]
        h, w = f.shape[:2]
        scale = 480 / h
        full = cv2.resize(f, (int(w * scale), 480), interpolation=cv2.INTER_NEAREST)
        cy, cx = h // 2, w // 2
        crop = f[cy - h // 5:cy + h // 5, cx - h // 5:cx + h // 5]
        crop = cv2.resize(crop, (480, 480), interpolation=cv2.INTER_NEAREST)
        row = np.hstack([full, np.full((480, 8, 3), 255, np.uint8), crop])
        cv2.putText(row, Path(p).parent.name, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
        rows.append(row)
    w = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 0, 8, 0, w - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for r in rows]
    cv2.imwrite(str(out), np.vstack(rows))


def main():
    if sys.argv[1] == "sheet":
        sheet(sys.argv[2], sys.argv[3:])
        return
    if sys.argv[1] == "bars":
        for p in sys.argv[2:]:
            print(f"{Path(p).parent.name:12}", {k: round(v, 2) for k, v in bar_edges(p).items()})
        return
    print(f"{'source':34}" + "".join(f"{k:>13}" for k in KEYS))
    for p in sys.argv[2:]:
        m = metrics(p)
        print(f"{'/'.join(Path(p).parts[-3:-1])[:33]:34}" + "".join(f"{m[k]:13.2f}" for k in KEYS))


if __name__ == "__main__":
    main()
