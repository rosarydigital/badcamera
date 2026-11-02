"""The sound side of a film: rooms, generated horror sounds, a local library with licence tracking, Freesound, take sync and loudness."""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np

from .audio import CACHE, NOMINAL
from .gpu import DATA
from .output import SR, ffmpeg

LIBRARY = DATA / "library"
INDEX = LIBRARY / "index.json"


def write_wav(path, x):
    x = np.asarray(x, "f8")
    x = np.stack([x, x], axis=1) if x.ndim == 1 else x
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("i2").tobytes())


def read_audio(path, rate=SR, channels=2):
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(path), "-vn", "-ac", str(channels), "-ar", str(rate), "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, "i2").astype("f8") / 32768
    return x.reshape(-1, channels) if channels > 1 else x


# ---- rooms ----

# Real spaces, by file name in FL Studio's impulse library (recorded by Soundiron). They're read from your own install and never shipped.
REAL_ROOMS = {
    "Hallway": "IMP downstairs_hallway_front.wv", "Long corridor": "IMP upwnstairs_hallway_back.wv", "Stairwell": "IMP stairwell_inner_open.wv", "Tower stairs": "IMP tower_stairwell.wv",
    "Narrow stairs": "IMP narrow_stairs.wv", "Bedroom": "IMP bedroom.wv", "Living room": "IMP family_room.wv", "Bathroom": "IMP bathroom.wv", "Tiled entry": "IMP entry_way_tile.wv",
    "Classroom": "IMP classroom.wv", "Cafeteria": "IMP cafeteria_back_wide.wv", "Dark warehouse": "IMP warehouse_hall_dark_a.wv", "Workshop": "IMP workshop_large_room_dark.wv",
    "Ruined building": "IMP brick_building_small_ruin.wv", "Inside a van": "IMP cargo_van_interior.wv", "Outhouse": "IMP outhouse_empty.wv", "Cave": "IMP Cave - Chamber.wv", "Church": "IMP church_2_far.wv",
    "Forest": "IMP forest_medium.wv", "Graveyard": "IMP graveyard_air.wv", "Open grave": "IMP graveyard_open_grave.wv", "Behind a door": "IMP library_door_closed_back.wv",
    "Under a desk": "IMP desk_under.wv", "Inside an oven": "IMP oven_closed.wv", "Bunker": "IMP bunker_a.wv", "Tunnel": "IMP tunnel_a.wv", "Parking garage": "IMP parking_garage_far.wv",
    "Storm drain": "IMP stormdrain_culvert_pipe_b.wv",
}
# Stand-ins for a computer without those files: decay seconds, brightness Hz, wet level, early-reflection spacing in ms.
FALLBACK = {"Hallway": (0.95, 3500, 0.42, 19), "Stairwell": (1.7, 4500, 0.5, 31), "Bedroom": (0.28, 5000, 0.28, 7), "Bathroom": (0.65, 7000, 0.45, 5), "Dark warehouse": (3.2, 3000, 0.6, 47),
            "Behind a door": (0.22, 520, 0.25, 4)}
ROOMS = {"None": None, **dict.fromkeys(REAL_ROOMS), "Through a wall": None}
MUFFLED = {"Through a wall": (0.25, 260)}  # dry level and cutoff: a barrier eats the highs


def impulse_root():
    for pattern in ("/run/media/*/*/Program Files/Image-Line/FL Studio */Data/Patches/Impulses", "C:/Program Files/Image-Line/FL Studio */Data/Patches/Impulses",
                    str(Path.home() / ".wine/drive_c/Program Files/Image-Line/FL Studio */Data/Patches/Impulses")):
        hit = sorted(glob.glob(pattern))
        if hit:
            return Path(hit[-1])
    return None


def find_impulse(room):
    root, name = impulse_root(), REAL_ROOMS.get(room)
    if root and name:
        hit = next(root.rglob(glob.escape(name)), None)
        if hit:
            return hit
    return None


def lowpass(x, cutoff):
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(np.fft.rfft(x) / np.sqrt(1 + (f / cutoff) ** 4), len(x))


def impulse(room):
    """A stereo impulse response for a space: the real recording when it's here, otherwise a stand-in."""
    f = find_impulse(room)
    if f:
        ir = read_audio(f)
    else:
        decay, bright, _, spacing = FALLBACK.get(room, (0.3, 3000, 0.3, 7))
        n = int(SR * decay * 1.3)
        t = np.arange(n) / SR
        tail = np.random.default_rng(sum(map(ord, room))).standard_normal(n) * 10 ** (-3 * t / decay)
        tail = lowpass(tail, bright)
        ir = np.stack([tail, tail], axis=1)
    return ir / max(np.sqrt((ir ** 2).sum(axis=0).max()), 1e-9)


def apply_room(x, room):
    """x: stereo float. The convolved signal replaces the dry one, because a real impulse already holds the direct sound.
    Fast convolution, block by block, so long files stay in memory limits."""
    if room == "None" or room not in ROOMS:
        return x
    if room in MUFFLED:
        dry, cut = MUFFLED[room]
        return np.stack([lowpass(x[:, c], cut) for c in (0, 1)], axis=1) * dry
    ir = impulse(room)
    block = SR * 8
    size = 2 ** int(np.ceil(np.log2(block + len(ir))))
    H = [np.fft.rfft(ir[:, c], size) for c in (0, 1)]
    out = np.zeros((len(x) + len(ir), 2))
    for start in range(0, len(x), block):
        seg = x[start:start + block]
        for ch in (0, 1):
            y = np.fft.irfft(np.fft.rfft(seg[:, ch], size) * H[ch], size)[:len(seg) + len(ir)]
            out[start:start + len(y), ch] += y
    y = out[:len(x)]
    y = y * np.sqrt((x ** 2).mean() / max((y ** 2).mean(), 1e-12))  # same loudness going out as coming in
    return y * min(1.0, 0.98 / max(np.abs(y).max(), 1e-6))


# ---- library ----

def load_index():
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_index(items):
    LIBRARY.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1), encoding="utf-8")
    tmp.replace(INDEX)


# What the sound pack fetches: (category, search, how many). Real recordings only, CC0 only, picked by community rating.
PACK = (("Footsteps", "footsteps concrete", 5), ("Footsteps", "footsteps wood floor", 5), ("Footsteps", "footsteps gravel", 3), ("Footsteps", "running footsteps", 4),
        ("Doors", "door slam", 5), ("Doors", "door creak", 5), ("Doors", "door knock", 4), ("Doors", "door open close", 4), ("Creaks", "floor creak", 5), ("Creaks", "wood creak", 4),
        ("Body", "scared breathing", 4), ("Body", "heavy breathing", 4), ("Body", "heartbeat", 3), ("Body", "scream", 4), ("Body", "gasp", 3),
        ("Ambience", "room tone", 5), ("Ambience", "empty room ambience", 4), ("Ambience", "wind outside", 4), ("Ambience", "night forest crickets", 4), ("Ambience", "rain on window", 3),
        ("Ambience", "fluorescent light hum", 3), ("Ambience", "old house ambience", 4), ("Electric", "radio static", 4), ("Electric", "tv static", 3), ("Electric", "vhs tape", 3),
        ("Impacts", "thud", 4), ("Impacts", "body fall", 4), ("Impacts", "metal clang", 4), ("Impacts", "glass break", 4), ("Impacts", "metal scrape", 3),
        ("Horror", "horror drone", 5), ("Horror", "horror ambience", 5), ("Horror", "riser tension", 4), ("Stingers", "horror stinger", 5), ("Stingers", "jump scare", 4), ("Horror", "whispers", 4))
AVOID = ("music", "synth", "game", "8bit", "8-bit", "chiptune", "loop-kit", "beat", "melody", "voice-over", "preview")


def quality_filter(duration=(0.5, 45)):
    return f'license:"Creative Commons 0" duration:[{duration[0]} TO {duration[1]}] avg_rating:[3.5 TO *] num_ratings:[2 TO *]'


def install_pack(token, progress=None, api=None):
    """Fetch the sound pack from Freesound into the library. Safe to run again: it only adds what's missing."""
    items = load_index()
    have = {i.get("id") for i in items}
    added = 0
    for n, (category, query, count) in enumerate(PACK):
        q = {"query": query, "token": token, "fields": FIELDS + ",avg_rating,num_ratings", "filter": quality_filter(), "sort": "rating_desc", "page_size": 25}
        with urllib.request.urlopen(f"{api or API}/search/text/?{urllib.parse.urlencode(q)}", timeout=20) as r:
            found = json.load(r)["results"]
        got = 0
        for s_ in found:
            words = f"{s_['name']} {' '.join(s_.get('tags', []))}".lower()
            if got >= count or any(w in words for w in AVOID):
                continue
            got += 1
            if s_["id"] in have:
                continue
            res = dict(id=s_["id"], name=s_["name"], author=s_["username"], license=s_["license"], url=s_["url"], preview=s_["previews"]["preview-hq-mp3"], duration=s_["duration"],
                       tags=f"{query} {' '.join(s_.get('tags', []))}")
            try:
                e = freesound_add(res, items, category)
            except OSError:
                continue
            items = load_index()
            have.add(s_["id"])
            added += 1
            if progress:
                progress(f"Sound pack: {added} added, {e['name'][:30]}")
        time.sleep(1.1)  # the API allows 60 requests a minute
    return added


def scan_folder(root, source, licence, category):
    """Index a folder of sounds where it sits. Nothing is copied, and it's safe to run again."""
    items = load_index()
    known = {i["path"] for i in items}
    for f in sorted(Path(root).rglob("*")):
        if f.suffix.lower() in (".wav", ".flac", ".aif", ".aiff", ".mp3", ".ogg") and str(f) not in known:
            items.append(dict(name=f.stem.replace(".M", ""), path=str(f), category=category, tags=f.stem.replace("FS", "footsteps").replace("BF", "body fall"), source=source, author=source, license=licence, url=""))
    save_index(items)
    return items


FAIRLIGHT_LICENCE = "Fairlight licence: DaVinci Resolve projects only"


def find_fairlight():
    """Blackmagic's free library, wherever it's unpacked or installed."""
    for pattern in ("/run/media/*/*/Blackmagic_Fairlight_Sound_Library*/Sound Library/Media Files", "/run/media/*/*/Program Files/Blackmagic Design/Fairlight Sound Library/Media Files",
                    "C:/Program Files/Blackmagic Design/Fairlight Sound Library/Media Files", "/opt/resolve/Fairlight/Media Files"):
        hit = glob.glob(pattern)
        if hit:
            return hit[0]
    return None


def prepare_library():
    """Drop the old generated sounds and pick up the Fairlight library if it's on this computer."""
    items = load_index()
    if any(i["source"] == "BadCamera" for i in items):
        save_index([i for i in items if i["source"] != "BadCamera"])
        shutil.rmtree(LIBRARY / "starter", ignore_errors=True)
    root = find_fairlight()
    if root and not any(i["source"] == "Fairlight" for i in load_index()):
        scan_folder(root, "Fairlight", FAIRLIGHT_LICENCE, "Fairlight")
    return load_index()


def search_local(items, query="", category="All"):
    words = query.lower().split()
    return [i for i in items if (category == "All" or i["category"] == category) and all(w in f"{i['name']} {i['tags']} {i['category']}".lower() for w in words)]


def licence_kind(text_):
    """Plain-language class of a licence. 'commercial' is False where selling a film with it isn't allowed."""
    t = (text_ or "").lower()
    if "resolve projects only" in t:
        return dict(label="Finish in Resolve", commercial=False, credit=False)
    if "your own" in t:
        return dict(label="Your files", commercial=True, credit=False)
    if "noncommercial" in t or "by-nc" in t or "non-commercial" in t or "sampling" in t:
        return dict(label="Non-commercial", commercial=False, credit=True)
    if "publicdomain/zero" in t or "cc0" in t or "creative commons 0" in t:
        return dict(label="CC0", commercial=True, credit=False)
    if "attribution" in t or "/by/" in t or "cc by" in t or "cc-by" in t:
        return dict(label="Credit required", commercial=True, credit=True)
    return dict(label="Check licence", commercial=False, credit=True)


# ---- Freesound ----

API = "https://freesound.org/apiv2"
FIELDS = "id,name,username,license,previews,duration,tags,url"


def freesound_search(query, token, cc0_only=True, page=1, api=API):
    """Search with a plain API key. Returns [{name, author, license, url, preview, duration, tags}]."""
    q = {"query": query, "token": token, "fields": FIELDS, "page_size": 30, "page": page}
    if cc0_only:
        q["filter"] = 'license:"Creative Commons 0"'
    with urllib.request.urlopen(f"{api}/search/text/?{urllib.parse.urlencode(q)}", timeout=15) as r:
        data = json.load(r)
    return [dict(id=s["id"], name=s["name"], author=s["username"], license=s["license"], url=s["url"], preview=s["previews"]["preview-hq-mp3"], duration=s["duration"],
                 tags=" ".join(s.get("tags", []))) for s in data["results"]]


def freesound_add(result, items=None, category="Freesound"):
    """Save a result into the library as a converted WAV. The HQ preview is what an API key allows; full originals need a user OAuth login."""
    items = load_index() if items is None else items
    folder = LIBRARY / "freesound"
    folder.mkdir(parents=True, exist_ok=True)
    mp3, out = folder / f"{result['id']}.mp3", folder / f"{result['id']}.wav"
    with urllib.request.urlopen(result["preview"], timeout=60) as r:
        mp3.write_bytes(r.read())
    subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(mp3), "-ar", str(SR), "-ac", "2", str(out)], check=True)
    mp3.unlink()
    entry = dict(id=result["id"], name=result["name"], path=str(out), category=category, tags=result.get("tags", ""), source="Freesound", author=result["author"], license=result["license"], url=result["url"])
    items = [i for i in items if i["path"] != str(out)] + [entry]
    save_index(items)
    return entry


def credits(tl, items=None):
    """(text, warnings) for sounds in a project: who to credit, and what can't be used in a film you sell."""
    items = {i["path"]: i for i in (load_index() if items is None else items)}
    lines, warn = [], []
    for path in sorted({s.path for s in tl.sounds}):
        i = items.get(path)
        if i is None:
            lines.append(f"{Path(path).name}: your own file, check its rights")
            continue
        k = licence_kind(i["license"])
        if k["credit"]:
            lines.append(f'"{i["name"]}" by {i["author"]} ({i["source"]}) {i["license"]} {i["url"]}'.strip())
        if not k["commercial"]:
            warn.append(f'{i["name"]}: {k["label"]}')
    return "\n".join(lines), warn


# ---- take sync ----

def find_offset(camera_path, recorder_path, rate=4000, max_seconds=300):
    """Seconds to skip into the recorder file to line it up with camera audio, plus how sure the match is (0-1)."""
    def env(p):
        x = read_audio(p, rate, 1)[:rate * max_seconds]
        return x - x.mean()
    a, b = env(camera_path), env(recorder_path)
    n = 2 ** int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.fft.rfft(b, n) * np.conj(np.fft.rfft(a, n)), n)
    peak = int(np.abs(c).argmax())
    lag = peak if peak < n // 2 else peak - n
    score = float(np.abs(c).max() / (np.sqrt((a ** 2).sum() * (b ** 2).sum()) + 1e-9))
    return lag / rate, min(score, 1.0)


# ---- loudness ----

LOUDNESS = {"YouTube (-14 LUFS)": -14.0, "Streaming (-16 LUFS)": -16.0, "Broadcast (-23 LUFS)": -23.0, "Theatrical trailer (-27 LUFS)": -27.0}


def measure_lufs(wav):
    """Integrated loudness and true peak of a file, as measured by ffmpeg's EBU R128 meter."""
    err = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-i", str(wav), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    tail = err[err.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    p = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    return float(i.group(1)) if i else -70.0, float(p.group(1)) if p else -70.0
