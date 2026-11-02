"""Found-footage features, checked by measuring real renders and exported files.

Run from the project root: python -m tests.test_story
"""
import json
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import moderngl
import numpy as np

from badcamera import audio, editor, presets, story
from badcamera.gpu import GPU
from badcamera.output import SR, ffmpeg, probe
from tests.test_editor import frames, make_clip, pcm, quiet_tone

FF = ffmpeg()


def export(tl, g, worker, path, variant="As edited", epoch=1_700_000_000):
    ex = editor.Exporter(tl, worker, path, epoch=epoch, variant=variant)
    while not ex.step(g, budget=1.0):
        time.sleep(0.005)
    assert not ex.error, ex.error
    return path


def rgb_frames(path, w=64, h=36):
    raw = subprocess.run([FF, "-loglevel", "error", "-i", str(path), "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype("f4")


def base(clip):
    tl = editor.Timeline()
    tl.clips.append(editor.Clip(clip, probe(clip)))
    return tl


def test_damage(g, worker, clip, tmp):
    tl = base(clip)
    tl.events.append({"t": 2.0, "d": 0.5, "kind": "Signal loss", "amount": 1.0})
    tl.events.append({"t": 3.2, "d": 0.4, "kind": "Static burst", "amount": 1.0})
    f = rgb_frames(export(tl, g, worker, tmp / "e.mp4")).mean(axis=(1, 2, 3))
    assert abs(f[45] - f[10]) < 1 or f[45] < 40, "signal loss should be near-black"
    assert f[100] > f[10] + 20, ("static should brighten the frame", f[100], f[10])
    assert abs(f[75] - f[10]) < 6, "faults must end when their window does"


def test_audio_events(worker, clip):
    tl = base(clip)
    worker.wait(tl.audio_keys())
    t0 = 1.0  # the first beep
    n = SR // 10
    clean = tl.mix(worker, t0, n)
    tl.events.append({"t": 0.9, "d": 0.4, "kind": "Mic overload", "amount": 1.0})
    over = tl.mix(worker, t0, n)
    assert np.abs(over).mean() > np.abs(clean).mean() * 1.3, "overload should be hotter"
    tl.events = [{"t": 0.9, "d": 0.4, "kind": "Audio dropout", "amount": 1.0}]
    assert np.abs(tl.mix(worker, t0, n)).max() < 0.01
    # Tape slowdown: the beep's pitch falls.
    tone = lambda x: np.fft.rfftfreq(len(x), 1 / SR)[np.abs(np.fft.rfft(x * np.hanning(len(x)))).argmax()]  # noqa: E731
    tl.events = []
    plain = tl.mix(worker, 1.02, 3000)[:, 0]
    tl.events = [{"t": 0.85, "d": 0.4, "kind": "Tape slowdown", "amount": 1.0}]
    slow = tl.mix(worker, 1.02, 3000)[:, 0]
    assert tone(slow) < tone(plain) * 0.75, (tone(slow), tone(plain))
    # Same result however playback chops up the buffers.
    tl.events = [{"t": 0.9, "d": 0.4, "kind": "Wind buffet", "amount": 1.0}]
    whole = tl.mix(worker, 0.95, 4800)
    parts = np.vstack([tl.mix(worker, 0.95 + i * 1200 / SR, 1200) for i in range(4)])
    assert np.abs(whole - parts).max() < 1e-3, "buffer size changed the sound"


def test_age(g, worker, clip, tmp):
    tl = base(clip)
    tl.age_start, tl.age_end = 0.0, 1.0
    assert story.age_at(tl, 0) == 0 and abs(story.age_at(tl, tl.duration) - 1) < 1e-9
    f = rgb_frames(export(tl, g, worker, tmp / "age.mp4"))
    assert np.abs(f[-5] - f[5]).mean() > 3, "the end of the film should look worn"


def test_power(g, worker, clip, tmp):
    tl = base(clip)
    c = tl.clips[0]
    c.power_on, c.battery = True, True
    worker.wait(tl.audio_keys())
    x = tl.mix(worker, 0.0, SR // 4)
    assert np.abs(x).max() > 0.1, "power-on should thump"
    f = rgb_frames(export(tl, g, worker, tmp / "p.mp4")).mean(axis=(1, 2, 3))
    assert f[0] < 8, ("starts dark", f[0])
    assert f[-2] < 3, ("battery kills the picture", f[-2])
    assert max(f[4:30]) > 45, "exposure overshoots on wake"
    b = rgb_frames(export(tl, g, worker, tmp / "p2.mp4"), 640, 360)
    icon = np.ptp(b[-40:-20, 300:330, 560:590].mean(axis=(1, 2, 3)))
    assert icon > 2, "battery icon should blink"


def test_motion(tmp):
    rms = {}
    for kind in ("Standing", "Walking", "Running", "Panicked"):
        m = np.array([story.motion_at(kind, t / 30, 1.0) for t in range(900)])
        rms[kind] = float(np.sqrt((m[:, :2] ** 2).mean()))
    assert rms["Standing"] < rms["Walking"] < rms["Running"] < rms["Panicked"] * 1.3, rms
    # Measuring a real clip: shake a known picture and get that shake back.
    w, h, fps = 320, 180, 15
    rng = np.random.default_rng(3)
    base_img = (rng.random((h // 4, w // 4)) * 255).astype(np.uint8)
    import cv2
    tex = cv2.resize(base_img, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
    path = tmp / "shake.mp4"
    p = subprocess.Popen([FF, "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "10",
                          "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for i in range(60):
        dx = int(12 * np.sin(i * 1.3))
        p.stdin.write(tex[h // 2: h // 2 + h, w // 2 + dx: w // 2 + dx + w].tobytes())
    p.stdin.close()
    p.wait()
    d = story.motion_from_video(path)
    amp = np.ptp(np.array(d["x"])) * 320
    assert 12 < amp < 40, ("should recover about +-12 px of shake", amp)
    c = editor.Clip(path, probe(path))
    c.motion, c.motion_file = "From video", str(path)
    v = editor.moved(c, 1.0)
    assert v["move_x"] != 0.0 and v["zoom"] > 1.0


def test_story_clock(g, worker, clip, tmp):
    tl = base(clip)
    tl.clips.append(editor.Clip(clip, probe(clip)))
    tl.clips[0].story = "1996-07-21 21:14:00"
    s = story.story_starts(tl)
    a, b = tl.clips
    assert abs(s[id(b)] - s[id(a)] - a.length) < 1e-6, "the next clip carries on from the last"
    assert story.parse_when("garbage") is None
    # On-screen text really shows the story date.
    e = presets.build({"steps": [{"type": "text_stamp", "params": {"text": "%Y"}}]})[0]
    g.begin_frame(0)
    g.wall = s[id(a)]
    assert e.format(g) == "1996"
    g.wall = None


def test_cards_cctv(g, worker, clip, tmp):
    p = story.make_card("Evidence tape", "EVIDENCE|TAPE 03", 2.0)
    info = probe(p)
    assert abs(info["duration"] - 2) < 0.15 and info["size"] == story.CARD_SIZE
    f = frames(p)[0]
    assert f.mean() > 16.5, "card should have text on it"
    s = editor.Session()
    s.tl.clips.append(editor.Clip(clip, probe(clip)))
    s.seek(1.0)
    s.add_card("Warning", "VIEWER DISCRETION ADVISED", 2.0)
    assert len(s.tl.clips) == 2 and s.tl.clips[1].name.startswith("warning")
    q = editor.Session()
    q.cctv([clip] * 4, "Quad split", length=3.0)
    assert len(q.tl.overlays) == 4 and sorted(c.rect[0] for c in q.tl.overlays) == [0, 0, 0.5, 0.5]
    assert "CAM 03" in [e.v["text"] for e in q.tl.overlays[2].steps if e.type == "text_stamp"][0]
    out = rgb_frames(export(q.tl, g, worker, tmp / "quad.mp4"))
    assert out.std() > 3
    q2 = editor.Session()
    q2.cctv([clip, clip], "Switcher", every=1.0, length=4.0)
    assert len(q2.tl.clips) == 4 and abs(q2.tl.duration - 4) < 0.01


def test_overlay(g, worker, clip, tmp):
    white = tmp / "white.mp4"
    subprocess.run([FF, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=320x180:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(white)], check=True)
    tl = base(clip)
    o = editor.Clip(white, probe(white))
    o.at, o.rect = 0.5, [0.5, 0.0, 0.5, 0.5]
    tl.overlays.append(o)
    f = rgb_frames(export(tl, g, worker, tmp / "o.mp4")).mean(axis=3)
    assert f[45, 8, 48] > 200 and f[45, 28, 16] < 80, (f[45, 8, 48], f[45, 28, 16])
    assert f[3, 8, 48] < 80 and f[85, 8, 48] < 80, "overlay obeys its start and end"


def test_sounds_stems(g, worker, clip, tmp):
    tl = base(clip)
    t = quiet_tone("Room tone", 20)
    s = editor.Sound(t, probe(t, need_video=False))
    assert abs(tl.duration - probe(clip)["duration"]) < 0.01
    tl.sounds.append(s)
    assert abs(tl.duration - probe(clip)["duration"]) < 0.01, "a long sound must not lengthen the film"
    tl.clips[0].audio = "VHS linear SP"
    worker.wait(tl.audio_keys())
    x = tl.mix(worker, 2.0, SR // 2, parts=("sound",))  # a quiet part of the video
    assert np.sqrt((x ** 2).mean()) > 1e-3, "sound track should play"
    folder = editor.export_stems(tl, worker, tmp / "stems")
    read = lambda n: np.frombuffer(wave.open(str(folder / n)).readframes(10 ** 8), "i2").astype("f8")  # noqa: E731
    full, parts = read("full_mix.wav"), read("dialogue.wav") + read("noise.wav") + read("sound.wav")
    assert np.abs(full - parts).max() < 3, "stems must sum back to the mix"
    assert np.sqrt((read("noise.wav") ** 2).mean()) > 1, "noise stem shouldn't be empty"


def test_denoise(tmp):
    rng = np.random.default_rng(4)
    t = np.arange(SR * 6) / SR
    x = 0.15 * np.sin(2 * np.pi * 300 * t) * ((t % 1) < 0.5) + 0.02 * rng.standard_normal(len(t))
    path = tmp / "noisy.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("i2").tobytes())
    gap = (t % 1 > 0.6) & (t > 2)
    level = {}
    for d in audio.DENOISE:
        out = tmp / "dn.s16"
        audio.render_to(path, None, out, denoise=d)
        y = np.fromfile(out, "i2").reshape(-1, 2)[:, 0].astype("f8") / 32768
        level[d] = np.sqrt((y[: len(gap)][gap[: len(y)]] ** 2).mean())
    print("denoise floor dB", {k: round(20 * np.log10(v), 1) for k, v in level.items()})
    assert level["Light"] < level["Off"] * 0.5 and level["Strong"] < level["Light"] * 0.7, level


def test_scrub_proxy(clip, tmp):
    long = tmp / "long.mp4"
    subprocess.run([FF, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=125", "-c:v", "libx264", "-preset", "ultrafast", "-g", "250", "-pix_fmt", "yuv420p", str(long)], check=True)
    c = editor.Clip(long, probe(long))
    px = editor.Proxies()
    assert px.want(c) == str(long)
    t0 = time.time()
    while str(long) in px.pending and time.time() - t0 < 120:
        time.sleep(0.2)
    proxy = px.want(c)
    assert proxy != str(long) and Path(proxy).exists(), "proxy wasn't made"
    assert abs(probe(proxy)["duration"] - 125) < 1

    def seek_time(dec, path, size, t):
        seq = dec.seq
        s = time.perf_counter()
        dec.seek(path, t, size, 30.0)
        while dec.seq == seq and time.perf_counter() - s < 5:
            time.sleep(0.001)
        return time.perf_counter() - s
    d = editor.Decoder()
    seek_time(d, str(long), (1920, 1080), 60.0)
    raw = np.median([seek_time(d, str(long), (1920, 1080), t) for t in (10.0, 80.0, 30.0, 100.0)])
    size = (854, 480)
    seek_time(d, proxy, size, 60.0)
    pro = np.median([seek_time(d, proxy, size, t) for t in (10.0, 80.0, 30.0, 100.0)])
    seek_time(d, proxy, size, 50.0)
    time.sleep(0.5)  # read-ahead fills in
    near = [seek_time(d, proxy, size, 50.0 + i / 30) for i in range(1, 8)]
    d.stop()
    print(f"seek ms: original {raw * 1000:.0f}, proxy {pro * 1000:.0f}, nearby scrub {np.median(near) * 1000:.1f}")
    assert pro < raw and np.median(near) < 0.02, (raw, pro, near)
    Path(proxy).unlink()


def test_queue_formats(g, worker, clip, tmp):
    s = editor.Session()
    s.worker = worker
    s.tl.clips.append(editor.Clip(clip, probe(clip)))
    s.tl.clips[0].steps = presets.build({"steps": [{"type": "desaturate", "params": {"amount": 1.0}}]})
    s.tl.fmt = "ProRes 4:3 in 16:9, 24"
    s.enqueue("As edited", str(tmp / "q1.mov"))
    s.tl.fmt = "YouTube 1080p 30"
    s.enqueue("Clean (no effects)", str(tmp / "q2.mp4"))
    s.next_job()
    done = []
    while s.exporter:
        if s.exporter.step(g, budget=1.0):
            done.append(s.exporter.path)
            assert not s.exporter.error, s.exporter.error
            s.exporter = None
            s.next_job()
    assert len(done) == 2
    a, b = probe(done[0]), probe(done[1])
    assert a["size"] == (1920, 1080) and abs(a["fps"] - 24) < 0.01 and b["size"] == (1920, 1080)
    codec = subprocess.run([FF, "-hide_banner", "-i", str(done[0])], capture_output=True, text=True).stderr
    assert "prores" in codec and "pcm_s24le" in codec
    f = rgb_frames(done[0], 160, 90)[30]
    assert f[:, :15].mean() < 3 and f[:, 40:120].mean() > 15, "4:3 picture needs bars at the sides"


def test_project_roundtrip(clip, tmp):
    tl = base(clip)
    t = quiet_tone("Wind outside", 20)
    tl.sounds.append(editor.Sound(t, probe(t, need_video=False)))
    c = tl.clips[0]
    c.story, c.note, c.power_on, c.motion, c.denoise = "1996-07-21 21:14", "Good take", True, "Walking", "Light"
    o = editor.Clip(clip, probe(clip))
    o.at, o.rect = 1.0, [0.5, 0.5, 0.5, 0.5]
    tl.overlays.append(o)
    tl.events.append({"t": 1.0, "d": 1.0, "kind": "Head jump", "amount": 0.5})
    tl.markers.append({"t": 2.0, "label": "Scene 12"})
    tl.age_end = 0.6
    p = tmp / "s.bcproj"
    editor.save_project(tl, p)
    other = editor.Timeline()
    assert editor.load_project(other, p) == []
    assert json.loads(other.state()) == json.loads(tl.state()), "project didn't round-trip"
    folder = editor.bundle_project(tl, tmp / "b")
    assert len(list((tmp / "b" / "media").iterdir())) == 2 and folder.exists()
    tl.commit()
    tl.markers.clear()
    tl.commit()
    tl.undo()
    assert tl.markers, "undo should cover markers"


def main():
    ctx = moderngl.create_standalone_context(backend="egl")
    g = GPU(ctx)
    worker = audio.Worker()
    editor.AUTOSAVE = Path(tempfile.mkdtemp()) / "autosave.bcproj"
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        clip = str(tmp / "clip.mp4")
        make_clip(clip)
        for name, fn, args in (("damage video", test_damage, (g, worker, clip, tmp)), ("damage audio", test_audio_events, (worker, clip)), ("tape age", test_age, (g, worker, clip, tmp)),
                               ("camera power", test_power, (g, worker, clip, tmp)), ("motion", test_motion, (tmp,)), ("story clock", test_story_clock, (g, worker, clip, tmp)),
                               ("cards, CCTV", test_cards_cctv, (g, worker, clip, tmp)), ("overlays", test_overlay, (g, worker, clip, tmp)), ("sound track, stems", test_sounds_stems, (g, worker, clip, tmp)),
                               ("noise reduction", test_denoise, (tmp,)), ("proxies, scrubbing", test_scrub_proxy, (clip, tmp)), ("queue, formats", test_queue_formats, (g, worker, clip, tmp)),
                               ("projects", test_project_roundtrip, (clip, tmp))):
            fn(*args)
            print(f"ok {name}", flush=True)
    print("all story checks passed")


if __name__ == "__main__":
    main()
