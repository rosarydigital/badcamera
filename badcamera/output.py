import queue
import subprocess
import threading
import time
from pathlib import Path

import cv2

from .gpu import DATA

CAPTURES = DATA / "captures"


def stamp_path(ext):
    CAPTURES.mkdir(exist_ok=True)
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


class Recorder:
    """Pipes raw RGB frames to ffmpeg on a worker thread so a slow encoder never stalls rendering."""

    def __init__(self):
        self.proc, self.path = None, None

    def start(self, w, h, fps):
        self.path = stamp_path("mp4")
        # shortcut: libx264 on CPU only; switch to h264_vaapi if 720p60 encoding can't keep up
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(self.path)],
            stdin=subprocess.PIPE)
        self.size, self.q = (w, h), queue.Queue(maxsize=8)
        threading.Thread(target=self._pump, args=(self.proc, self.q), daemon=True).start()

    @staticmethod
    def _pump(proc, q):
        while (frame := q.get()) is not None:
            proc.stdin.write(frame)
        proc.stdin.close()
        proc.wait()

    def write(self, rgb):
        if self.proc and rgb.shape[1::-1] == self.size:
            try:
                self.q.put_nowait(rgb.tobytes())
            except queue.Full:
                pass  # encoder behind: drop a frame rather than stall the live view

    def stop(self):
        if self.proc:
            self.q.put(None)
            self.proc = None
        return self.path
