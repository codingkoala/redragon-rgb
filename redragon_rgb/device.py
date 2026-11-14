"""Low-level driver for the Redragon M711 Redragon RGB lighting.

Transport: USB control transfers (HID SET_REPORT) on vendor interface 2,
through libusb-1.0 loaded with ctypes. hidraw cannot be used because the
M711's report descriptor declares no Feature reports (the ioctl fails with
EINVAL), as measured by the m711-port project.

Protocol (from dokutan/mouse_m908, OpenRGB and SK2674/m711-port):
  * 16-byte frames, report ID 0x02, wValue 0x0302, wIndex 2
  * unlock   02 F5 00            (every sequence must start with it)
  * write    02 F3 <addr lo> <addr hi> <count> 00 00 00 <data...>
  * apply    02 F1 02 04
  * lock     02 F5 01            (every sequence must end with it)
  * LED of profile n (0..4): 0x0449 + 8n -> R, G, B, mode1, speed (1 fast - 8 slow), mode2
  * brightness of profile n:  0x044F + 8n -> 1 byte (1..3)

Color, mode1 and mode2 are always written together: writing only the
color while a color-less mode is active freezes the LED animation.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass

from .effects import Effect

VENDOR_ID = 0x04D9
PRODUCT_IDS = {0xFC30: "Redragon M711 Cobra", 0xFC62: "Redragon M711-FPS-1 Cobra FPS"}
INTERFACE = 2
PROFILES = 5

FRAME_SIZE = 16
REPORT_ID = 0x02
SET_REPORT_REQTYPE = 0x21  # host->device, class, interface
SET_REPORT = 0x09
WVALUE_FEATURE_2 = 0x0302  # report type 3 (feature) << 8 | report id 2
TIMEOUT_MS = 1000

ADDR_LED = 0x0449
ADDR_BRIGHTNESS = 0x044F
PROFILE_STRIDE = 8

SPEED_RANGE = (1, 8)
BRIGHTNESS_RANGE = (1, 3)


EFFECTS: list[Effect] = [
    # code = (mode1, mode2)
    Effect("static", "Static", "Solid color", (0x01, 0x02), True, False),
    Effect("breathing", "Breathing", "The color slowly pulses", (0x01, 0x04), True, True),
    Effect("flashing", "Flashing", "The color blinks", (0x01, 0x10), True, True),
    Effect("rainbow", "Rainbow", "Continuous cycle through all colors", (0x01, 0x08), False, True, "always"),
    Effect("rainbow_breathing", "Rainbow breathing", "Pulses, changing color each time", (0x01, 0x01), False, True, "always"),
    Effect("wave", "Wave", "Flowing wave of colors", (0x02, 0x00), False, True, "always"),
    Effect("reactive", "Reactive", "Lights up when you click", (0x07, 0x00), True, True),
    Effect("off", "Off", "LEDs off", (0x00, 0x00), is_off=True),
]
EFFECTS_BY_KEY = {e.key: e for e in EFFECTS}


class DeviceError(Exception):
    pass


class DeviceNotFound(DeviceError):
    pass


class DevicePermissionError(DeviceError):
    pass


# --- libusb binding --------------------------------------------------------
LIBUSB_ERROR_ACCESS = -3
LIBUSB_ERROR_NO_DEVICE = -4
LIBUSB_ERROR_BUSY = -6

_lib = None


def _libusb() -> ctypes.CDLL:
    global _lib
    if _lib is not None:
        return _lib
    name = ctypes.util.find_library("usb-1.0") or "libusb-1.0.so.0"
    try:
        lib = ctypes.CDLL(name)
    except OSError as exc:
        raise DeviceError("libusb-1.0 not found: sudo apt install libusb-1.0-0") from exc
    vp = ctypes.c_void_p
    lib.libusb_init.argtypes = [ctypes.POINTER(vp)]
    lib.libusb_exit.argtypes = [vp]
    lib.libusb_exit.restype = None
    lib.libusb_get_device_list.argtypes = [vp, ctypes.POINTER(ctypes.POINTER(vp))]
    lib.libusb_get_device_list.restype = ctypes.c_ssize_t
    lib.libusb_free_device_list.argtypes = [ctypes.POINTER(vp), ctypes.c_int]
    lib.libusb_free_device_list.restype = None
    lib.libusb_get_device_descriptor.argtypes = [vp, ctypes.c_char_p]
    lib.libusb_open.argtypes = [vp, ctypes.POINTER(vp)]
    lib.libusb_close.argtypes = [vp]
    lib.libusb_close.restype = None
    lib.libusb_set_auto_detach_kernel_driver.argtypes = [vp, ctypes.c_int]
    lib.libusb_claim_interface.argtypes = [vp, ctypes.c_int]
    lib.libusb_release_interface.argtypes = [vp, ctypes.c_int]
    lib.libusb_control_transfer.argtypes = [
        vp, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint16,
        ctypes.c_char_p, ctypes.c_uint16, ctypes.c_uint,
    ]
    lib.libusb_strerror.argtypes = [ctypes.c_int]
    lib.libusb_strerror.restype = ctypes.c_char_p
    _lib = lib
    return lib


def _err(lib, code: int) -> str:
    return lib.libusb_strerror(code).decode(errors="replace")


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    product_id: int


def _scan(lib, ctx):
    """Yield (device pointer, product id) for every connected M711."""
    devs = ctypes.POINTER(ctypes.c_void_p)()
    n = lib.libusb_get_device_list(ctx, ctypes.byref(devs))
    if n < 0:
        raise DeviceError(f"libusb: {_err(lib, n)}")
    return devs, n


def _matching(lib, devs, n):
    desc = ctypes.create_string_buffer(18)
    for i in range(n):
        dev = devs[i]
        if lib.libusb_get_device_descriptor(dev, desc) != 0:
            continue
        raw = desc.raw
        vid = raw[8] | raw[9] << 8
        pid = raw[10] | raw[11] << 8
        if vid == VENDOR_ID and pid in PRODUCT_IDS:
            yield dev, pid


def find_devices() -> list[DeviceInfo]:
    lib = _libusb()
    ctx = ctypes.c_void_p()
    if lib.libusb_init(ctypes.byref(ctx)) != 0:
        raise DeviceError("Could not initialize libusb")
    try:
        devs, n = _scan(lib, ctx)
        try:
            return [DeviceInfo(PRODUCT_IDS[pid], pid) for _, pid in _matching(lib, devs, n)]
        finally:
            lib.libusb_free_device_list(devs, 1)
    finally:
        lib.libusb_exit(ctx)


class CobraMouse:
    """An open M711. Use as a context manager; the vendor interface is
    claimed only for the lifetime of the object."""

    def __init__(self):
        self._lib = lib = _libusb()
        self._ctx = ctypes.c_void_p()
        self._handle = ctypes.c_void_p()
        self._claimed = False
        if lib.libusb_init(ctypes.byref(self._ctx)) != 0:
            raise DeviceError("Could not initialize libusb")
        try:
            self._open()
        except Exception:
            self.close()
            raise

    def _open(self) -> None:
        lib = self._lib
        devs, n = _scan(lib, self._ctx)
        try:
            found = next(_matching(lib, devs, n), None)
            if found is None:
                raise DeviceNotFound("No Redragon M711 found. Is the mouse plugged in?")
            dev, pid = found
            self.info = DeviceInfo(PRODUCT_IDS[pid], pid)
            rc = lib.libusb_open(dev, ctypes.byref(self._handle))
        finally:
            lib.libusb_free_device_list(devs, 1)
        if rc == LIBUSB_ERROR_ACCESS:
            raise DevicePermissionError(
                "Permission denied on the USB device. Install the udev rule: "
                "sudo ./install-udev.sh"
            )
        if rc != 0:
            raise DeviceError(f"Could not open the device: {_err(lib, rc)}")
        lib.libusb_set_auto_detach_kernel_driver(self._handle, 1)
        rc = lib.libusb_claim_interface(self._handle, INTERFACE)
        if rc == LIBUSB_ERROR_BUSY:
            raise DeviceError("Interface busy: close OpenRGB or any other program using the mouse.")
        if rc != 0:
            raise DeviceError(f"Could not claim the interface: {_err(lib, rc)}")
        self._claimed = True

    def close(self) -> None:
        lib = self._lib
        if self._claimed:
            lib.libusb_release_interface(self._handle, INTERFACE)  # re-attaches usbhid
            self._claimed = False
        if self._handle:
            lib.libusb_close(self._handle)
            self._handle = ctypes.c_void_p()
        if self._ctx:
            lib.libusb_exit(self._ctx)
            self._ctx = ctypes.c_void_p()

    def __enter__(self) -> "CobraMouse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- frames ----------------------------------------------------------
    def _send(self, payload: bytes) -> None:
        frame = bytearray(FRAME_SIZE)
        frame[: len(payload)] = payload
        rc = self._lib.libusb_control_transfer(
            self._handle, SET_REPORT_REQTYPE, SET_REPORT, WVALUE_FEATURE_2,
            INTERFACE, bytes(frame), FRAME_SIZE, TIMEOUT_MS,
        )
        if rc == LIBUSB_ERROR_NO_DEVICE:
            raise DeviceNotFound("The mouse was disconnected.")
        if rc != FRAME_SIZE:
            raise DeviceError(f"Communication error: {_err(self._lib, rc) if rc < 0 else rc}")

    def _lock(self, locked: bool) -> None:
        self._send(bytes([REPORT_ID, 0xF5, 0x01 if locked else 0x00]))

    def _write(self, address: int, data: bytes) -> None:
        self._send(bytes([REPORT_ID, 0xF3, address & 0xFF, address >> 8, len(data), 0, 0, 0]) + data)

    def _apply(self) -> None:
        self._send(bytes([REPORT_ID, 0xF1, 0x02, 0x04]))

    # -- public API ------------------------------------------------------
    def set_lighting(
        self,
        effect: Effect | str,
        color: tuple[int, int, int] = (255, 30, 60),
        speed: int = 4,
        brightness: int = 3,
    ) -> None:
        """Apply one lighting effect to all five profiles."""
        if isinstance(effect, str):
            effect = EFFECTS_BY_KEY[effect]
        r, g, b = (max(0, min(255, int(c))) for c in color)
        speed = max(SPEED_RANGE[0], min(SPEED_RANGE[1], int(speed)))
        # UI speed grows with the animation speed; the firmware byte is the
        # other way round (1 = fastest, 8 = slowest, verified on an M711).
        fw_speed = SPEED_RANGE[0] + SPEED_RANGE[1] - speed
        brightness = max(BRIGHTNESS_RANGE[0], min(BRIGHTNESS_RANGE[1], int(brightness)))
        led = bytes([r, g, b, effect.code[0], fw_speed, effect.code[1]])

        self._lock(False)
        try:
            for p in range(PROFILES):
                self._write(ADDR_LED + PROFILE_STRIDE * p, led)
                self._write(ADDR_BRIGHTNESS + PROFILE_STRIDE * p, bytes([brightness]))
            self._apply()
        finally:
            self._lock(True)
