"""Sound library, rooms, take sync, loudness, story tools and timeline exchange, checked by measurement.

Run from the project root: python -m tests.test_sound
"""
import http.server
import json
import subprocess
import tempfile
import threading
import time
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import moderngl
import numpy as np

from badcamera import audio, editor, exchange, output, presets, sound, story
from badcamera.gpu import GPU
from badcamera.output import SR, ffmpeg, probe
from tests.test_editor import make_clip, pcm, quiet_tone

FF = ffmpeg()


def base(clip):
    tl = editor.Timeline()
    tl.clips.append(editor.Clip(clip, probe(clip)))
    return tl


def tone_file(tmp, name, x):
    p = tmp / name
    sound.write_wav(p, x)
    return p


def test_rooms(tmp):
    t = np.arange(SR * 3) / SR
    click = (0.8 * np.sin(2 * np.pi * 1000 * t) * (t < 0.05))
    x = np.stack([click, click], axis=1)
    assert sound.impulse_root(), "FL Studio's impulses should be found on this machine"
    missing = [r for r in sound.REAL_ROOMS if not sound.find_impulse(r)]
    assert not missing, missing
    tail = {}
    for room in sound.REAL_ROOMS:
        y = sound.apply_room(x, room)
        assert np.isfinite(y).all() and np.abs(y).max() <= 1.0
        e = y[:, 0] ** 2
        tail[room] = float(np.flatnonzero(np.cumsum(e) >= e.sum() * 0.95)[0]) / SR  # time for 95% of the energy to arrive
    print("95% energy in:", {k: round(v, 2) for k, v in sorted(tail.items(), key=lambda kv: kv[1])})
    assert tail["Inside a van"] < tail["Stairwell"] < tail["Church"], tail
    noise = np.random.default_rng(1).standard_normal((SR, 2)) * 0.2
    y = sound.apply_room(noise, "Through a wall")
    f = np.fft.rfftfreq(SR, 1 / SR)
    assert np.abs(np.fft.rfft(y[:, 0]))[f > 2000].mean() < np.abs(np.fft.rfft(noise[:, 0]))[f > 2000].mean() * 0.1
    p = tone_file(tmp, "c.wav", x)
    out = tmp / "r.s16"
    audio.render_to(p, "Camcorder mic", out, space="Hallway")
    assert out.stat().st_size > SR
    keep = sound.impulse_root
    sound.impulse_root = lambda: None  # another computer, with no FL Studio
    assert np.isfinite(sound.apply_room(x, "Hallway")).all()
    sound.impulse_root = keep


def test_match_and_fades(worker, clip, tmp):
    tl = base(clip)
    tl.clips[0].audio = "Old landline"
    s = editor.Sound(tone_file(tmp, "n.wav", 0.3 * np.random.default_rng(2).standard_normal(SR * 3)), {"duration": 3.0, "audio": True, "size": None, "fps": 0.0}, 0.5)
    tl.sounds.append(s)
    assert tl.preset_of(s) == "Old landline", "a sound should take the clip's hardware"
    worker.wait(tl.audio_keys())
    x = tl.mix(worker, 1.0, SR // 2, parts=("sound",))[:, 0]
    f = np.fft.rfftfreq(len(x), 1 / SR)
    p = np.abs(np.fft.rfft(x)) ** 2
    assert p[f > 6000].sum() < p[(f > 300) & (f < 3000)].sum() * 0.02, "matched sound should be phone-band"
    s.audio, s.fade_in, s.fade_out = audio.ORIGINAL, 1.0, 1.0
    worker.wait(tl.audio_keys())
    rms = lambda t: float(np.sqrt((tl.mix(worker, t, 4800, parts=("sound",)) ** 2).mean()))  # noqa: E731
    assert rms(0.55) < rms(1.5) * 0.3 and rms(3.3) < rms(1.5) * 0.4, "fades should shape level"
    s.fade_in = s.fade_out = 0.01
    s.points = [[0.0, 1.0], [1.0, 0.0], [3.0, 0.0]]
    assert rms(2.0) < 1e-4 < rms(0.6), "volume points should ride the level"


def test_cut_all_tracks(clip, tmp):
    s = editor.Session()
    s.tl.clips.append(editor.Clip(clip, probe(clip)))
    o = s.add_overlay(clip)
    o.at = 0.0
    s.seek(1.0)
    assert s.cut() and len(s.tl.overlays) == 2 and s.tl.overlays[1].start == 1.0 and s.tl.overlays[1].at == 1.0
    t = quiet_tone("Room tone", 20)
    n = s.add_sound(t, 0.0)
    assert s.cut() and len(s.tl.sounds) == 2 and s.tl.sounds[1].at == 1.0 and abs(n.end - 1.0) < 1e-6
    s.clean_exit()


def test_sync(tmp):
    rng = np.random.default_rng(3)
    speech = np.convolve(rng.standard_normal(SR * 12), np.ones(40) / 40, "same") * (np.sin(np.arange(SR * 12) / SR * 3) > 0)
    camera = speech[:SR * 8] * 0.5 + rng.standard_normal(SR * 8) * 0.02  # noisy camera mic
    recorder = np.concatenate([np.zeros(int(2.25 * SR)), speech * 0.8])  # clean take, started 2.25 s earlier
    a, b = tone_file(tmp, "cam.wav", camera), tone_file(tmp, "rec.wav", recorder)
    offset, score = sound.find_offset(a, b)
    print(f"take sync: {offset:.3f}s (true 2.250), match {score:.2f}")
    assert abs(offset - 2.25) < 0.005 and score > 0.3


def test_loudness(worker, clip, tmp):
    s = editor.Session()
    s.worker = worker
    p = tone_file(tmp, "l.wav", 0.05 * np.sin(2 * np.pi * 440 * np.arange(SR * 8) / SR))
    subprocess.run([FF, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=30:d=8", "-i", str(p), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp / "lv.mp4")], check=True)
    s.tl.clips.append(editor.Clip(tmp / "lv.mp4", probe(tmp / "lv.mp4")))
    before, peak, gain = s.set_loudness(-14.0)
    w = tmp / "after.wav"
    worker.wait(s.tl.audio_keys())
    editor.write_wav(w, s.tl, worker)
    after, p2 = sound.measure_lufs(w)
    print(f"loudness: {before:.1f} -> {after:.1f} LUFS, peak {p2:.1f}")
    assert abs(after + 14) < 1.0 and p2 <= -0.5


class Fake(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        Fake.seen.append(self.path)
        if self.path.startswith("/apiv2/search/text"):
            body = json.dumps({"results": [{"id": 7, "name": "old door", "username": "someone", "license": "http://creativecommons.org/publicdomain/zero/1.0/", "url": "https://freesound.org/s/7/",
                                            "previews": {"preview-hq-mp3": f"http://127.0.0.1:{self.server.server_port}/p.mp3"}, "duration": 1.5, "tags": ["door"]},
                                           {"id": 8, "name": "nc door", "username": "other", "license": "https://creativecommons.org/licenses/by-nc/4.0/", "url": "https://freesound.org/s/8/",
                                            "previews": {"preview-hq-mp3": f"http://127.0.0.1:{self.server.server_port}/p.mp3"}, "duration": 2.0, "tags": []}]}).encode()
        else:
            body = Path(Fake.mp3).read_bytes()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_library(clip, tmp):
    keep = sound.INDEX
    sound.LIBRARY, sound.INDEX = tmp / "lib", tmp / "lib" / "index.json"
    root = tmp / "fl"
    root.mkdir()
    tone_file(root, "Door Close FS.M.wav", 0.2 * np.sin(np.arange(SR) / 20))
    items = sound.scan_folder(root, "Fairlight", sound.FAIRLIGHT_LICENCE, "Fairlight")
    assert sound.search_local(items, "footsteps door"), "FS should search as footsteps"
    assert sound.licence_kind(sound.FAIRLIGHT_LICENCE)["commercial"] is False
    assert sound.find_fairlight(), "the Fairlight library should be found on this machine"
    Fake.mp3 = tmp / "p.mp3"
    subprocess.run([FF, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=500:d=1", "-c:a", "libmp3lame", str(Fake.mp3)], check=True)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{srv.server_port}/apiv2"
    found = sound.freesound_search("door", "KEY", True, api=api)
    q = Fake.seen[-1]
    assert "token=KEY" in q and "Creative+Commons+0" in q and len(found) == 2
    sound.freesound_search("door", "KEY", False, api=api)
    assert "filter" not in Fake.seen[-1]
    a, b = sound.freesound_add(found[0]), sound.freesound_add(found[1])
    assert Path(a["path"]).exists() and probe(a["path"], need_video=False)["duration"] > 0.9
    tl = base(clip)
    for e in (a, b):
        tl.sounds.append(editor.Sound(e["path"], probe(e["path"], need_video=False)))
    text, warn = sound.credits(tl)
    assert "nc door" in text and len(warn) == 1 and "Non-commercial" in warn[0], (text, warn)
    assert sound.install_pack("KEY", api=api) >= 0 and all(Path(i["path"]).exists() for i in sound.load_index())
    srv.shutdown()


def test_story_tools(g, worker, clip, tmp):
    tl = base(clip)
    story.realism_pass(tl, 5, 40.0)
    first = json.dumps(tl.events)
    assert len(tl.events) > 3
    story.realism_pass(tl, 5, 40.0)
    assert json.dumps(tl.events) == first, "same seed, same faults"
    story.realism_pass(tl, 6, 40.0)
    assert json.dumps(tl.events) != first
    tl.events.append({"t": 0.5, "d": 0.1, "kind": "Head jump", "amount": 1.0})
    story.realism_pass(tl, 6, 0.1)
    assert any(not e.get("auto") for e in tl.events), "a re-run must keep hand-placed faults"
    s = editor.Session()
    s.tl.clips.append(editor.Clip(clip, probe(clip)))
    s.seek(1.5)
    s.add_scare({"path": str(quiet_tone("Room tone", 10))})
    assert {e["kind"] for e in s.tl.events} >= {"Camera jolt", "Static burst"} and s.tl.sounds[0].track == 1
    script = "Title: Test\n\nINT. BASEMENT - NIGHT\n\nShe stops.\n\n.THE ATTIC\n\nEXT. WOODS - DAY\n\nint. not a heading in lower case\n"
    scenes = story.parse_script(script)
    assert [x["title"] for x in scenes] == ["INT. BASEMENT - NIGHT", "THE ATTIC", "EXT. WOODS - DAY"], scenes
    # Reels keep their own timelines, and render into the master.
    r = editor.Session()
    r.worker = worker
    r.tl.clips.append(editor.Clip(clip, probe(clip)))
    r.switch_reel("Reel 2")
    assert not r.tl.clips
    r.tl.clips.append(editor.Clip(clip, probe(clip)))
    r.tl.clips.append(editor.Clip(clip, probe(clip)))
    r.switch_reel("Main")
    assert len(r.tl.clips) == 1
    p = tmp / "reels.bcproj"
    r.tl.reels["Reel 2"] = r.tl.reels["Reel 2"]
    editor.save_project(r.tl, p)
    assert r.nest_reel("Reel 2")
    r.next_job()
    ex = r.exporter
    while not ex.step(g, 1.0):
        time.sleep(0.005)
    assert not ex.error, ex.error
    r.job_done(ex)
    assert len(r.tl.clips) == 2 and abs(r.tl.clips[1].length - probe(clip)["duration"] * 2) < 0.3
    Path(ex.path).unlink()
    other = editor.Timeline()
    editor.load_project(other, p)
    assert "Reel 2" in other.reels


def test_exchange(clip, tmp):
    tl = base(clip)
    tl.split(1.5)
    o = editor.Clip(clip, probe(clip))
    o.at, o.end = 0.5, 2.0
    tl.overlays.append(o)
    t = quiet_tone("Wind outside", 10)
    s = editor.Sound(t, probe(t, need_video=False), 0.25)
    s.end, s.track = 3.0, 1
    tl.sounds.append(s)
    edl = exchange.export_edl(tl, tmp / "a.edl")
    text = Path(edl).read_text()
    assert text.count(" AA/V ") == 2 and "00:00:01:15" in text, text
    xml = exchange.export_fcpxml(tl, tmp / "a.fcpxml")
    root = ET.parse(xml).getroot()
    assert root.tag == "fcpxml" and len(root.findall(".//spine/asset-clip")) == 2 and root.find(".//asset-clip/asset-clip") is not None
    refs = {a.get("id") for a in root.findall(".//asset")}
    assert all(c.get("ref") in refs for c in root.findall(".//asset-clip"))
    import opentimelineio as otio
    tlo = otio.adapters.read_from_file(str(exchange.export_otio(tl, tmp / "a.otio")))
    kinds = [(x.kind, len(list(x.find_clips()))) for x in tlo.tracks]
    assert kinds == [("Video", 2), ("Video", 1), ("Audio", 1)], kinds
    assert abs(tlo.tracks[0].duration().to_seconds() - tl.layout()[-1][2]) < 0.05


def test_clean_feed(tmp):
    r, c = output.Recorder(), output.Recorder()
    r.start(320, 240, 30, path=tmp / "look.mp4")
    c.start(320, 240, 30, path=tmp / "look_clean.mp4")
    t0 = time.time()
    while time.time() - t0 < 1.5:
        r.write(np.zeros((240, 320, 3), np.uint8))
        c.write(np.full((240, 320, 3), 200, np.uint8))
        time.sleep(0.02)
    r.stop()
    c.stop()
    r.saved.wait(10)
    c.saved.wait(10)
    assert abs(probe(tmp / "look_clean.mp4")["duration"] - 1.5) < 0.2


def main():
    ctx = moderngl.create_standalone_context(backend="egl")
    g = GPU(ctx)
    worker = audio.Worker()
    editor.AUTOSAVE = Path(tempfile.mkdtemp()) / "autosave.bcproj"
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        clip = str(tmp / "clip.mp4")
        make_clip(clip)
        for name, fn, args in (("rooms", test_rooms, (tmp,)), ("match, fades, points", test_match_and_fades, (worker, clip, tmp)), ("cut on every track", test_cut_all_tracks, (clip, tmp)),
                               ("take sync", test_sync, (tmp,)), ("loudness", test_loudness, (worker, clip, tmp)), ("library, Freesound, credits", test_library, (clip, tmp)),
                               ("story tools, reels", test_story_tools, (g, worker, clip, tmp)), ("timeline exchange", test_exchange, (clip, tmp)), ("clean feed", test_clean_feed, (tmp,))):
            fn(*args)
            print(f"ok {name}", flush=True)
    print("all sound checks passed")


if __name__ == "__main__":
    main()
