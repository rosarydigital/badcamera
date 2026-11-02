"""Headless editor checks: timeline edits, undo, keyframes, projects, and real exports measured with ffmpeg.

Run from the project root: python -m tests.test_editor
"""
import hashlib
import json
import random
import subprocess
import tempfile
import time
from pathlib import Path

import moderngl
import numpy as np

from badcamera import audio, editor, effects, presets, transform
from badcamera.gpu import GPU
from badcamera.output import SR, ffmpeg, probe

FF = ffmpeg()


def make_clip(path, dur=4, flash_at=(1.0, 3.0), fps=30, size="640x360", tone=440):
    """Dark video with a white flash and a beep at the same moments, so sync can be measured from the file."""
    bright = "+".join(f"between(t,{t},{t + 0.1})" for t in flash_at)
    beep = "+".join(f"between(t\\,{t}\\,{t + 0.1})" for t in flash_at)
    subprocess.run([FF, "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x202020:s={size}:r={fps}:d={dur}",
                    "-f", "lavfi", "-i", f"aevalsrc=0.5*sin(2*PI*{tone}*t)*({beep}):s={SR}:d={dur}",
                    "-vf", f"drawbox=c=white:t=fill:enable='{bright}'", "-c:v", "libx264", "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", str(path)], check=True)


def quiet_tone(name="tone", seconds=20):
    """A plain sound file for tests."""
    out = Path(tempfile.gettempdir()) / f"badcamera_test_{name.replace(' ', '_')}_{seconds}.wav"
    if not out.exists():
        subprocess.run([FF, "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.05:sample_rate={SR}:seed=1", "-t", str(seconds), "-ac", "2", str(out)], check=True)
    return out


def frames(path):
    """Mean brightness per frame, and the fps."""
    info = probe(path)
    w, h = 64, 36
    raw = subprocess.run([FF, "-loglevel", "error", "-i", str(path), "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).mean(axis=(1, 2)), info["fps"]


def pcm(path):
    raw = subprocess.run([FF, "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, "i2").astype("f8") / 32768


def onsets(x, rate, threshold):
    above = x > threshold
    return (np.flatnonzero(above[1:] & ~above[:-1]) + 1) / rate


def export(tl, g, worker, path):
    ex = editor.Exporter(tl, worker, path, epoch=1_700_000_000)
    while not ex.step(g, budget=1.0):
        time.sleep(0.005)
    assert not ex.error, ex.error
    return path


def test_timeline(clip):
    info = probe(clip)
    assert abs(info["duration"] - 4) < 0.1 and info["size"] == (640, 360) and info["audio"] and abs(info["fps"] - 30) < 0.01, info
    tl = editor.Timeline()
    tl.clips.append(editor.Clip(clip, info))
    tl.commit()
    assert tl.split(1.5) == 1 and len(tl.clips) == 2
    tl.commit()
    assert abs(tl.clips[0].end - 1.5) < 1e-6 and abs(tl.clips[1].start - 1.5) < 1e-6
    assert abs(tl.duration - info["duration"]) < 1e-6
    assert tl.split(0.01) is None  # too close to the edge to cut
    tl.trim(1, start=2.0)
    tl.commit()
    assert abs(tl.clips[1].length - (info["duration"] - 2.0)) < 1e-6
    tl.move(1, 0)
    tl.commit()
    assert tl.clips[0].start == 2.0
    tl.delete(0)
    tl.commit()
    assert len(tl.clips) == 1
    for want in (2, 2, 2, 1):
        tl.undo()
        assert len(tl.clips) == want, (len(tl.clips), want)
    assert len(tl.clips) == 1 and abs(tl.clips[0].length - info["duration"]) < 1e-6  # back to the original uncut clip
    tl.redo()
    assert len(tl.clips) == 2
    # Layout during a transition: two clips showing, overlapping by its length.
    tl.clips[0].trans, tl.clips[0].trans_d = "Crossfade", 0.5
    shown, p, kind = tl.at(tl.clips[0].length - 0.25)
    assert len(shown) == 2 and kind == "Crossfade" and abs(p - 0.5) < 1e-6
    assert abs(tl.duration - (info["duration"] - 0.5)) < 1e-6


def test_keyframes(clip):
    info = probe(clip)
    c = editor.Clip(clip, info)
    c.steps = presets.build({"steps": [{"type": "vignette", "params": {}}]})
    e = c.steps[0]
    e.keys = {}
    e.v["strength"] = 0.0
    editor.set_key(e, "strength", 1.0, 0.0)
    editor.set_key(e, "strength", 3.0, 1.0)
    for t, want in ((0.0, 0.0), (1.0, 0.0), (2.0, 0.5), (2.5, 0.75), (3.0, 1.0), (9.0, 1.0)):
        editor.apply_keys(e, t)
        assert abs(e.v["strength"] - want) < 1e-6, (t, e.v["strength"], want)
    editor.toggle_key(e, "strength", 3.0)
    assert len(e.keys["strength"]) == 1
    editor.toggle_key(e, "strength", 1.0)
    assert "strength" not in e.keys
    editor.set_key(c.tx, "rotate", 0.0, 0.0)
    editor.set_key(c.tx, "rotate", 2.0, 90.0)
    editor.apply_keys(c.tx, 1.0)
    assert c.tx.v["rotate"] == 45.0


def test_transform():
    t = transform.new()
    m = transform.matrix(t, (640, 360), (640, 360)).reshape(3, 3).T
    assert np.allclose(m @ [0.25, 0.75, 1], [0.25, 0.75, 1]), "identity must map uv to itself"
    t["rotate"] = 90.0
    m = transform.matrix(t, (640, 360), (640, 360)).reshape(3, 3).T
    assert np.allclose(m @ [0.5, 0.5, 1], [0.5, 0.5, 1]), "rotation keeps the centre"
    t = transform.new({"zoom": 2.0})
    m = transform.matrix(t, (640, 360), (640, 360)).reshape(3, 3).T
    assert np.allclose(m @ [1.0, 1.0, 1], [0.75, 0.75, 1]), "2x zoom shows the middle half"
    t = transform.new({"stretch": 2.0})
    m = transform.matrix(t, (640, 360), (640, 360)).reshape(3, 3).T
    assert np.allclose(m @ [1.0, 1.0, 1], [0.75, 1.0, 1]), "stretch only touches width"
    m = transform.matrix(transform.new(), (640, 480), (640, 360)).reshape(3, 3).T  # 16:9 into 4:3 letterboxes
    assert np.allclose((m @ [0.5, 0.0, 1])[:2], [0.5, 0.5 - 0.5 * 480 / 360])


def test_export(g, worker, clip, tmp):
    info = probe(clip)
    tl = editor.Timeline()
    a = editor.Clip(clip, info)
    a.steps = presets.build({"steps": [{"type": "color_grade", "params": {"contrast": 0.1}}]})
    tl.clips.append(a)
    out = export(tl, g, worker, tmp / "a.mp4")
    got = probe(out)
    assert abs(got["duration"] - info["duration"]) < 0.1, got
    bright, fps = frames(out)
    flashes = onsets(bright, fps, 128)
    x = np.abs(pcm(out))
    env = np.convolve(x, np.ones(240) / 240, "same")
    beeps = onsets(env, SR, 0.1)
    assert len(flashes) == 2 and len(beeps) == 2, (flashes, beeps)
    offset = beeps - flashes
    print(f"A/V offset: {[f'{o * 1000:.1f} ms' for o in offset]}")
    assert np.abs(offset).max() < 0.02, offset

    # Cut out the middle: the beep at 3 s must arrive at 2 s, flash with it.
    tl = editor.Timeline()
    tl.clips.append(editor.Clip(clip, info))
    tl.split(1.5)
    tl.split(2.5)
    tl.delete(1)
    out = export(tl, g, worker, tmp / "b.mp4")
    bright, fps = frames(out)
    fl = onsets(bright, fps, 128)
    bp = onsets(np.convolve(np.abs(pcm(out)), np.ones(240) / 240, "same"), SR, 0.1)
    assert len(fl) == 2 and abs(fl[1] - 2.0) < 0.05 and abs(bp[1] - 2.0) < 0.05, (fl, bp)

    # Same project twice = same frames, even with a random-driven effect and a date on screen.
    tl = editor.Timeline()
    c = editor.Clip(clip, info)
    c.steps = presets.build({"steps": [{"type": "frame_rate", "params": {"fps": 20.0, "jitter": 0.5}}, {"type": "flash", "params": {"flicker": 0.5}},
                                       {"type": "text_stamp", "params": {"text": "%H:%M:%S"}}, {"type": "noise", "params": {"amount": 0.05}}]})
    tl.clips.append(c)
    hashes = []
    for i in range(2):
        random.seed(i)  # unrelated state must not matter
        p = export(tl, g, worker, tmp / f"d{i}.mp4")
        raw = subprocess.run([FF, "-loglevel", "error", "-i", str(p), "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"], capture_output=True).stdout
        hashes.append(hashlib.sha256(raw).hexdigest())
    assert hashes[0] == hashes[1], "exports differ"

    # A transition exports at the shorter length, and PAL format really is PAL.
    tl = editor.Timeline()
    tl.clips += [editor.Clip(clip, info), editor.Clip(clip, info)]
    tl.clips[0].trans = "Tape rewind"
    tl.fmt = "PAL 768x576 25"
    got = probe(export(tl, g, worker, tmp / "t.mp4"))
    assert got["size"] == (768, 576) and abs(got["fps"] - 25) < 0.01 and abs(got["duration"] - (info["duration"] * 2 - 0.5)) < 0.12, got


def test_projects(g, worker, clip, tmp):
    info = probe(clip)
    tl = editor.Timeline()
    c = editor.Clip(clip, info)
    c.steps = presets.build({"steps": [{"type": "vignette", "params": {"strength": 0.3}}]})
    c.steps[0].keys = {"strength": [[0.0, 0.1], [1.0, 0.9]]}
    c.tx.v["rotate"] = 12.0
    c.audio, c.gain, c.trans = "Old landline", 0.7, "Crossfade"
    tl.clips += [c, editor.Clip(clip, info)]
    tl.split(1.0)
    path = tmp / "p.bcproj"
    editor.save_project(tl, path)
    other = editor.Timeline()
    assert editor.load_project(other, path) == []
    assert json.loads(other.state()) == json.loads(tl.state()), "project didn't round-trip"
    # Bundle: moves with its media to another folder.
    folder = tmp / "bundle"
    b = editor.bundle_project(tl, folder)
    moved = tmp / "moved"
    folder.rename(moved)
    other = editor.Timeline()
    assert editor.load_project(other, moved / b.name) == []
    assert all(Path(x.path).is_file() and moved in Path(x.path).parents for x in other.clips)
    assert len(list((moved / "media").iterdir())) == 1
    # Missing media is reported, not fatal.
    (moved / "media" / Path(clip).name).unlink()
    other = editor.Timeline()
    assert len(editor.load_project(other, moved / b.name)) == 3
    # Crash recovery: autosave survives, and is picked up.
    s = editor.Session()
    s.add_files([clip])
    editor.save_project(s.tl, editor.AUTOSAVE)
    s2 = editor.Session()
    assert s2.recover and not s2.recover_autosave() and len(s2.tl.clips) == 1
    s2.clean_exit()
    assert not editor.AUTOSAVE.exists()


def test_presets(tmp):
    import shutil
    keep = tmp / "user_backup"
    if presets.USER.exists():
        shutil.copytree(presets.USER, keep)
    try:
        d = {"name": "Share Me", "steps": [{"type": "vignette", "enabled": True, "params": {"strength": 0.2}}]}
        presets.export_file(d, tmp / "share.json")
        assert presets.import_file(tmp / "share.json") == "Share Me"
        assert presets.import_file(tmp / "share.json") == "Share Me 2"  # never overwrites
        assert any(p["name"] == "Share Me 2" for p in presets.load_all())
        (tmp / "bad.json").write_text('{"name": "x", "steps": [{"type": "nope"}]}')
        try:
            presets.import_file(tmp / "bad.json")
            raise AssertionError("bad preset accepted")
        except ValueError:
            pass
        presets.save("styles", [])  # must not clobber the styles file
        presets.USER_STYLES.write_text('{"vignette": {"Mine": {"strength": 0.5}}}')
        assert "Mine" in presets.styles("vignette") and all("name" in p for p in presets.load_all()), "styles.json must not load as a preset"
    finally:
        shutil.rmtree(presets.USER, ignore_errors=True)
        if keep.exists():
            shutil.copytree(keep, presets.USER)


def main():
    ctx = moderngl.create_standalone_context(backend="egl")
    g = GPU(ctx)
    worker = audio.Worker()
    editor.AUTOSAVE = Path(tempfile.mkdtemp()) / "autosave.bcproj"
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        clip = tmp / "clip.mp4"
        make_clip(clip)
        clip = str(clip)
        for name, fn, args in (("timeline", test_timeline, (clip,)), ("keyframes", test_keyframes, (clip,)), ("transform", test_transform, ()),
                               ("export", test_export, (g, worker, clip, tmp)), ("projects", test_projects, (g, worker, clip, tmp)),
                               ("presets", test_presets, (tmp,))):
            fn(*args)
            print(f"ok {name}")
    print("all editor checks passed")


if __name__ == "__main__":
    main()
