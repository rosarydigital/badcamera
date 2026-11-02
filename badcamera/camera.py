import os
import threading
import time

import cv2


class Camera(threading.Thread):
    """Grabs frames in the background; the renderer always takes the newest one."""

    def __init__(self, source, size, fps):
        super().__init__(daemon=True)
        self.is_file = not (source.startswith("/dev/") or source.isdigit())
        backend = cv2.CAP_ANY if self.is_file else cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_V4L2
        self.cap = cv2.VideoCapture(int(source) if source.isdigit() else source, backend)
        self.ok = self.cap.isOpened()  # no camera is fine: the Editor tab still works
        if self.ok and not self.is_file:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
            self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.file_dt = 1 / (self.cap.get(cv2.CAP_PROP_FPS) or 30)
        self.frame, self.seq, self.fps, self.running = None, 0, 0.0, True

    def run(self):
        last = time.perf_counter()
        while self.running and self.ok:
            ok, f = self.cap.read()
            if not ok:
                if self.is_file:  # loop test videos
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                time.sleep(0.01)
                continue
            if self.is_file:
                time.sleep(max(0.0, self.file_dt - (time.perf_counter() - last)))
            now = time.perf_counter()
            self.fps = 0.9 * self.fps + 0.1 / max(now - last, 1e-6)
            last = now
            self.frame, self.seq = f, self.seq + 1

    def stop(self):
        self.running = False
        if self.is_alive():
            self.join(timeout=1)
        self.cap.release()
