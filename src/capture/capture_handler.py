import cv2
import numpy as np
from typing import Optional, List


class CaptureHandler:
    """
    Captures video frames from a capture card device (e.g. EZCap).

    The capture card appears as a video device accessible via OpenCV's
    VideoCapture. Device index 0 is usually the webcam; the capture card
    is typically index 1 or higher depending on connected devices.

    Usage:
        handler = CaptureHandler(device_index=1)
        handler.open()
        frame = handler.grab_frame()   # numpy BGR array
        handler.close()
    """

    def __init__(self, device_index: int = 0, width: int = 1280, height: int = 720):
        self.device_index = device_index
        self.width = width
        self.height = height
        self._cap: Optional[cv2.VideoCapture] = None

    def open(self):
        self._cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Could not open capture device at index {self.device_index}. "
                f"Try a different device index (0, 1, 2...)."
            )
        # Do NOT force a resolution — let the device use its native output.
        # Forcing 1280x720 on a 640x480 virtual cam breaks frame reads.

    def grab_frame(self) -> Optional[np.ndarray]:
        """Grab a single BGR frame. Returns None if capture fails."""
        if self._cap is None or not self._cap.isOpened():
            return None
        ret, frame = self._cap.read()
        return frame if ret else None

    def grab_frames(self, count: int, interval: float = 0.1) -> List[np.ndarray]:
        """Grab multiple frames separated by `interval` seconds."""
        import time
        frames = []
        for _ in range(count):
            frame = self.grab_frame()
            if frame is not None:
                frames.append(frame)
            time.sleep(interval)
        return frames

    def close(self):
        if self._cap:
            self._cap.release()
            self._cap = None

    @staticmethod
    def list_devices(max_check: int = 8) -> List[int]:
        """Return indexes of all available video capture devices."""
        available = []
        for i in range(max_check):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available.append(i)
                cap.release()
        return available

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()
