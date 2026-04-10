# `src/capture/capture_handler.py` — Documentation

## Purpose

Reads video frames from the Switch screen via an HDMI capture card.

The capture card (e.g. Vantisan, EZCap) plugs between the Switch dock and the
PC via USB. It appears to Windows as a standard video capture device.
OBS Studio captures the card's output and re-exposes it as an **OBS Virtual
Camera**, which OpenCV can read just like a webcam.

---

## Hardware Chain

```
Nintendo Switch Dock
    ↓ HDMI
Capture Card
    ↓ USB 3.0
PC (Windows)
    ↓ OBS Studio reads the card
OBS Virtual Camera (device index 3 typically)
    ↓ OpenCV VideoCapture
CaptureHandler.grab_frame()
    ↓ numpy BGR array
ShinyDetector.check()
```

---

## Class: `CaptureHandler`

### Constructor
```python
CaptureHandler(device_index: int = 0, width: int = 1280, height: int = 720)
```
- `device_index` — OpenCV device index for the OBS Virtual Camera.
  Usually 0 (if no webcam), 1, 2, or 3. Calibrate with `CaptureHandler.list_devices()`.
  For this project, the OBS Virtual Camera was found at **device index 3**.
- `width`, `height` — stored but NOT forced on the device. Forcing a resolution
  on an OBS Virtual Camera (which outputs 640×480) breaks frame reads with OpenCV.

---

### `open()`
Opens the OpenCV VideoCapture using `cv2.CAP_DSHOW` backend (Windows DirectShow).
Raises `RuntimeError` if the device cannot be opened.

> ℹ️ `cv2.CAP_DSHOW` is the correct backend for capture cards on Windows.
> Without it, some devices produce heavily delayed or corrupt frames.

---

### `grab_frame() -> np.ndarray | None`
Reads one frame from the capture device.

- Returns a BGR `numpy` array (OpenCV's native color format)
- Returns `None` if the capturedevice is not open or the read fails

---

### `grab_frames(count, interval=0.1) -> list[np.ndarray]`
Grabs `count` frames separated by `interval` seconds.
Used when the detector needs multiple frames to average out noise.

---

### `close()`
Releases the OpenCV VideoCapture and sets `self._cap = None`.

---

### `list_devices(max_check=8) -> list[int]`
Static method. Probes device indices 0 through `max_check-1` and returns
those that successfully open. Use this to discover which index is your
OBS Virtual Camera.

```python
>>> CaptureHandler.list_devices()
[0, 1, 3]   # 0=webcam, 1=capture card raw, 3=OBS virtual camera
```

---

### Context Manager Support (`__enter__` / `__exit__`)
`CaptureHandler` can be used with `with`:
```python
with CaptureHandler(device_index=3) as cap:
    frame = cap.grab_frame()
```
`open()` is called on enter, `close()` on exit.

---

## Coordinate System

Frames come out as BGR numpy arrays shaped `(height, width, 3)`.
Standard game resolution from OBS: **640 × 480 pixels**.

All detection regions (`POKEMON_SPRITE_REGION`, `BATTLE_REGION`, etc.) are
defined as `(top, left, bottom, right)` fractions of the frame dimensions,
so they work regardless of the actual pixel resolution.
