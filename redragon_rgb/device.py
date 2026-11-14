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
WVALUE_FEATURE_3 = 0x0303  # report id 3: 64-byte frames
GET_REPORT_REQTYPE = 0xA1  # device->host, class, interface
GET_REPORT = 0x01
REPLY_HEADER = 8
TIMEOUT_MS = 1000

ADDR_ACTIVE_PROFILE = 0x002C
ADDR_POLL = (0x0032, 0x0038)  # profiles 1-3, profiles 4-5
DPI_READ_BASES = (0x0042, 0x0102, 0x01B2, 0x0262, 0x0312)
DPI_WRITE_BASES = (0x0044, 0x0104, 0x01B4, 0x0264, 0x0314)
DPI_LEVELS = 5
DPI_FACTOR = 10000 / 225
DPI_CODE_RANGE = (4, 140)
DPI_RANGE = (200, 10000)
POLL_CODES = {1000: 1, 500: 2, 250: 4, 125: 8}
POLL_RATES = {v: k for k, v in POLL_CODES.items()}

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


def dpi_to_code(dpi: int) -> tuple[int, int]:
    """Nearest (code, high) pair the firmware can represent."""
    best = None
    for high in (0, 1):
        for code in range(DPI_CODE_RANGE[0], DPI_CODE_RANGE[1] + 1):
            err = abs(code * DPI_FACTOR * 2**high - dpi)
            if best is None or err < best[0]:
                best = (err, code, high)
    return best[1], best[2]


def code_to_dpi(code: int, high: int) -> int:
    return round(code * DPI_FACTOR * 2 ** (high & 1))


def quantize_dpi(dpi: int) -> int:
    """The DPI value the mouse will actually store for `dpi`."""
    return code_to_dpi(*dpi_to_code(dpi))


@dataclass
class DpiLevel:
    enabled: bool
    dpi: int


@dataclass
class Profile:
    levels: list[DpiLevel]
    poll_rate: int | None  # Hz, None if the byte is unknown


@dataclass
class Lighting:
    effect: str | None  # effect key, None if the firmware reports an unknown mode
    color: tuple[int, int, int]  # LED drive levels, as stored
    speed: int  # UI scale (higher = faster)
    brightness: int


@dataclass
class MouseState:
    active_profile: int  # 0..4
    profiles: list[Profile]


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
    def _send(self, payload: bytes, size: int = FRAME_SIZE, wvalue: int = WVALUE_FEATURE_2) -> None:
        frame = bytearray(size)
        frame[: len(payload)] = payload
        rc = self._lib.libusb_control_transfer(
            self._handle, SET_REPORT_REQTYPE, SET_REPORT, wvalue,
            INTERFACE, bytes(frame), size, TIMEOUT_MS,
        )
        self._check(rc, size)

    def _check(self, rc: int, expected: int | None) -> None:
        if rc == LIBUSB_ERROR_NO_DEVICE:
            raise DeviceNotFound("The mouse was disconnected.")
        if rc < 0 or (expected is not None and rc != expected):
            raise DeviceError(f"Communication error: {_err(self._lib, rc) if rc < 0 else rc}")

    def _read(self, address: int, count: int, report: int = 2) -> bytes:
        """Read `count` bytes at `address` (must be inside a lock/unlock pair)."""
        size, wvalue = (64, WVALUE_FEATURE_3) if report == 3 else (FRAME_SIZE, WVALUE_FEATURE_2)
        self._send(bytes([report, 0xF2, address & 0xFF, address >> 8, count]), size, wvalue)
        buf = ctypes.create_string_buffer(max(size, REPLY_HEADER + count))
        rc = self._lib.libusb_control_transfer(
            self._handle, GET_REPORT_REQTYPE, GET_REPORT, wvalue, INTERFACE, buf, len(buf), TIMEOUT_MS)
        self._check(rc, None)
        raw = buf.raw[:rc]
        # Header: <id> 08 <addr lo> <addr hi> <count> 00 fa fa. The echoed address
        # is not reliable (the firmware adds 0x6000 and clears bit 0 of odd
        # addresses: 0x0449 comes back as 0x6448), so only marker and count
        # are checked.
        if rc < REPLY_HEADER + count or raw[1] != 0x08 or raw[4] != count:
            raise DeviceError(f"Unexpected reply from the mouse at 0x{address:04x}: {raw[:16].hex(' ')}")
        return raw[REPLY_HEADER : REPLY_HEADER + count]

    def _lock(self, locked: bool) -> None:
        self._send(bytes([REPORT_ID, 0xF5, 0x01 if locked else 0x00]))

    def _write(self, address: int, data: bytes) -> None:
        self._send(bytes([REPORT_ID, 0xF3, address & 0xFF, address >> 8, len(data), 0, 0, 0]) + data)

    def _apply(self, what: int = 0x04) -> None:
        # 0x04 = lighting, 0x02 = DPI / report rate, 0x01 = profile
        self._send(bytes([REPORT_ID, 0xF1, 0x02, what]))

    def _session(self):
        """Context manager: unlock before, always lock again after."""
        mouse = self

        class _S:
            def __enter__(self):
                mouse._lock(False)

            def __exit__(self, *exc):
                mouse._lock(True)

        return _S()

    # -- profiles / DPI --------------------------------------------------
    def read_state(self) -> MouseState:
        with self._session():
            active = self._read(ADDR_ACTIVE_PROFILE, 1)[0]
            poll = self._read(ADDR_POLL[0], 10)
            profiles = []
            for p in range(PROFILES):
                raw = self._read(DPI_READ_BASES[p], 32, report=3)
                levels = []
                for j in range(DPI_LEVELS):
                    b = 2 + 6 * j
                    levels.append(DpiLevel(raw[b] != 0, code_to_dpi(raw[b + 1], raw[b + 2])))
                profiles.append(Profile(levels, POLL_RATES.get(poll[2 * p])))
        return MouseState(min(active, PROFILES - 1), profiles)

    def read_lighting(self, profile: int | None = None) -> Lighting:
        """Lighting of `profile` (0-4), or of the active profile if None."""
        with self._session():
            if profile is None:
                profile = min(self._read(ADDR_ACTIVE_PROFILE, 1)[0], PROFILES - 1)
            # R, G, B, mode1, speed, mode2, brightness (brightness is only
            # readable here; it is written at ADDR_BRIGHTNESS)
            led = self._read(ADDR_LED + PROFILE_STRIDE * profile, 7)
        effect = next((e.key for e in EFFECTS if e.code == (led[3], led[5])), None)
        fw_speed = max(SPEED_RANGE[0], min(SPEED_RANGE[1], led[4]))
        brightness = max(BRIGHTNESS_RANGE[0], min(BRIGHTNESS_RANGE[1], led[6]))
        return Lighting(effect, (led[0], led[1], led[2]), SPEED_RANGE[0] + SPEED_RANGE[1] - fw_speed, brightness)

    def write_profile(self, profile: int, levels: list[DpiLevel], poll_rate: int | None = None) -> None:
        """Write the DPI levels (and optionally the report rate) of one profile."""
        if not 0 <= profile < PROFILES:
            raise ValueError(f"Profile must be 1-{PROFILES}")
        if len(levels) != DPI_LEVELS:
            raise ValueError(f"Expected {DPI_LEVELS} DPI levels")
        if not any(lv.enabled for lv in levels):
            raise ValueError("At least one DPI level must stay enabled")
        if poll_rate is not None and poll_rate not in POLL_CODES:
            raise ValueError(f"Report rate must be one of {sorted(POLL_CODES)} Hz")
        for lv in levels:
            if not DPI_RANGE[0] <= lv.dpi <= DPI_RANGE[1]:
                raise ValueError(f"DPI must be {DPI_RANGE[0]}-{DPI_RANGE[1]} (got {lv.dpi})")
        with self._session():
            for j, lv in enumerate(levels):
                code, high = dpi_to_code(lv.dpi)
                self._write(DPI_WRITE_BASES[profile] + 6 * j, bytes([1 if lv.enabled else 0, code, high, code]))
            if poll_rate is not None:
                # read-modify-write so the other profiles keep their rate
                poll = bytearray(self._read(ADDR_POLL[0], 10))
                poll[2 * profile] = POLL_CODES[poll_rate]
                self._write(ADDR_POLL[0], bytes(poll[:6]))
                self._write(ADDR_POLL[1], bytes(poll[6:10]))
            self._apply(0x02)

    def set_active_profile(self, profile: int) -> None:
        if not 0 <= profile < PROFILES:
            raise ValueError(f"Profile must be 1-{PROFILES}")
        with self._session():
            self._write(ADDR_ACTIVE_PROFILE, bytes([profile, 0]))
            self._apply(0x01)

    # -- public API ------------------------------------------------------
    def set_lighting(
        self,
        effect: Effect | str,
        color: tuple[int, int, int] = (255, 30, 60),
        speed: int = 4,
        brightness: int = 3,
        profiles: list[int] | None = None,
    ) -> None:
        """Apply one lighting effect to the given profiles (0-4), default all five."""
        profiles = list(range(PROFILES)) if profiles is None else profiles
        if not profiles or any(not 0 <= p < PROFILES for p in profiles):
            raise ValueError(f"Profiles must be 1-{PROFILES}")
        if isinstance(effect, str):
            effect = EFFECTS_BY_KEY[effect]
        r, g, b = (max(0, min(255, int(c))) for c in color)
        speed = max(SPEED_RANGE[0], min(SPEED_RANGE[1], int(speed)))
        # UI speed grows with the animation speed; the firmware byte is the
        # other way round (1 = fastest, 8 = slowest, verified on an M711).
        fw_speed = SPEED_RANGE[0] + SPEED_RANGE[1] - speed
        brightness = max(BRIGHTNESS_RANGE[0], min(BRIGHTNESS_RANGE[1], int(brightness)))
        led = bytes([r, g, b, effect.code[0], fw_speed, effect.code[1]])

        with self._session():
            for p in profiles:
                self._write(ADDR_LED + PROFILE_STRIDE * p, led)
                self._write(ADDR_BRIGHTNESS + PROFILE_STRIDE * p, bytes([brightness]))
            self._apply(0x04)
