import queue
import re
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

import cv2

from .gpu import DATA, ROOT

CAPTURES = DATA / "captures"
SR = 48000


def ffmpeg():
    """The system ffmpeg when there is one (it has the GSM codec), otherwise the copy shipped with the app."""
    if path := shutil.which("ffmpeg"):
        return path
    for f in sorted((ROOT / "ffmpeg").glob("ffmpeg*")):
        return str(f)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise FileNotFoundError("ffmpeg") from None


def has_encoder(name):
    out = subprocess.run([ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return f" {name} " in out


def probe(path, need_video=True):
    """Duration, size, fps, rotation and audio presence, parsed from ffmpeg so no ffprobe has to ship with the app."""
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, errors="replace").stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    video = re.search(r"Stream #.*Video: (?!.*attached pic).*", err)
    size = video and re.search(r", (\d{2,5})x(\d{2,5})", video.group(0))
    if not need_video and dur and "Audio:" in err:
        h_, m, s = dur.groups()
        return {"duration": int(h_) * 3600 + int(m) * 60 + float(s), "size": None, "fps": 0.0, "audio": True}
    if not (dur and size):
        raise ValueError(f"{Path(path).name} isn't a video ffmpeg can read")
    fps = re.search(r"([\d.]+) fps", video.group(0)) or re.search(r"([\d.]+) tbr", video.group(0))
    rot = re.search(r"rotation of (-?[\d.]+) degrees", err) or re.search(r"rotate\s*: (-?[\d.]+)", err)
    w, h = int(size.group(1)), int(size.group(2))
    if rot and round(float(rot.group(1))) % 180 == 90:  # ffmpeg applies rotation metadata when it decodes
        w, h = h, w
    h_, m, s = dur.groups()
    return {"duration": int(h_) * 3600 + int(m) * 60 + float(s), "size": (w, h), "fps": float(fps.group(1)) if fps else 30.0,
            "audio": bool(re.search(r"Stream #.*Audio:", err))}


def stamp_path(ext):
    CAPTURES.mkdir(parents=True, exist_ok=True)
    return CAPTURES / f"badcam_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.{ext}"


def snapshot(rgb):
    p = stamp_path("png")
    cv2.imwrite(str(p), rgb[..., ::-1])
    return p


class VirtualCam:
    def __init__(self, device):
        self.device, self.cam, self.error = device, None, None

    def toggle(self, w, h, fps):
        if self.cam:
            self.cam.close()
            self.cam = None
            return
        try:
            import pyvirtualcam
            self.cam = pyvirtualcam.Camera(w, h, fps, fmt=pyvirtualcam.PixelFormat.RGB, device=self.device)
            self.error = None
        except Exception as ex:
            self.error = f"{ex} (is v4l2loopback loaded? see README)"

    def send(self, rgb):
        if self.cam and rgb.shape[1::-1] == (self.cam.width, self.cam.height):
            self.cam.send(rgb)


class Mic:
    """Records the microphone to a WAV while a video records. The offset lines it up with the first video frame."""

    def __init__(self, device, path):
        import sounddevice as sd
        self.path, self.file, self.offset, self.t0 = path, wave.open(str(path), "wb"), 0.0, None
        self.file.setnchannels(1)
        self.file.setsampwidth(2)
        self.file.setframerate(SR)
        self.stream = sd.RawInputStream(samplerate=SR, channels=1, dtype="int16", device=device, callback=self._audio)
        self.t0 = self.stream.time
        self.first = True
        self.stream.start()

    def _audio(self, data, frames, times, status):
        if self.first:
            self.offset, self.first = times.inputBufferAdcTime - self.t0, False
        self.file.writeframes(bytes(data))

    def stop(self):
        self.stream.stop()
        self.stream.close()
        self.file.close()


class Recorder:
    """Pipes raw RGB frames to ffmpeg on a worker thread so a slow encoder never stalls rendering.
    Frames are repeated or skipped against the clock, so the file plays at real speed at any render fps."""

    def __init__(self):
        self.proc, self.path, self.mic = None, None, None
        self.saved = threading.Event()

    def start(self, w, h, fps, mic_device=None, audio_preset=None, path=None):
        self.path = path or stamp_path("mp4")
        self.fps, self.written, self.t0 = fps, 0, None
        self.saved.clear()
        # shortcut: libx264 on CPU only; switch to h264_vaapi if 720p60 encoding can't keep up
        self.proc = subprocess.Popen(
            [ffmpeg(), "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(self.path)],
            stdin=subprocess.PIPE)
        self.mic = Mic(mic_device, self.path.with_suffix(".mic.wav")) if mic_device is not None else None
        self.audio_preset = audio_preset
        self.size, self.q = (w, h), queue.Queue(maxsize=8)
        threading.Thread(target=self._pump, args=(self.proc, self.q), daemon=True).start()

    def _pump(self, proc, q):
        while (item := q.get()) is not None:
            frame, copies = item
            for _ in range(copies):
                proc.stdin.write(frame)
        proc.stdin.close()
        proc.wait()
        if self.finished_mic:
            self._mux(self.finished_mic)
        self.saved.set()

    def _mux(self, mic):
        from . import audio
        out = self.path.with_suffix(".tmp.mp4")
        wet = audio.process_file(mic.path, self.audio_preset) if self.audio_preset else mic.path
        # Written into the samples rather than as a timestamp offset, which some players ignore.
        align = f"adelay={mic.offset * 1000:.1f}:all=1" if mic.offset >= 0 else f"atrim=start={-mic.offset:.4f},asetpts=PTS-STARTPTS"
        subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(self.path), "-i", str(wet), "-af", align,
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)], check=True)
        out.replace(self.path)
        for f in {mic.path, wet}:
            f.unlink(missing_ok=True)

    def write(self, rgb):
        if self.proc and rgb.shape[1::-1] == self.size:
            now = time.perf_counter()
            self.t0 = self.t0 or now
            due = int((now - self.t0) * self.fps) + 1 - self.written
            if due < 1:
                return  # rendering faster than the file's frame rate
            try:
                self.q.put_nowait((rgb.tobytes(), due))
                self.written += due
            except queue.Full:
                pass  # encoder behind: the next frame fills the gap rather than stall the live view

    finished_mic = None

    def stop(self):
        if self.proc:
            if self.mic:
                self.mic.stop()
            self.finished_mic, self.mic = self.mic, None
            self.q.put(None)
            self.proc = None
        return self.path
