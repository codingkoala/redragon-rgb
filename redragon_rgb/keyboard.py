"""Driver for Redragon keyboards with an EVision controller (K556: 320f:5000).

Transport: 64-byte HID output reports (report ID 0x04) on the vendor
interface (usage page 0xFF1C) via hidraw; the keyboard answers each
packet with a 64-byte input report.

Packet layout (from OpenRGB's EVisionKeyboardController):
  [0]    0x04 report id
  [1..2] checksum (little endian) of bytes 3..63
  [3]    command (0x01 begin, 0x02 end, 0x06 set parameter)
  [4]    data length
  [5]    parameter / offset
  [8..]  data
Set-parameter 0 with 8 bytes = mode, brightness (0-4), speed (5 slow - 0 fast),
direction, random-color flag, R, G, B.
"""

from __future__ import annotations

import os
import select
from dataclasses import dataclass
from pathlib import Path

from .effects import Effect

# (vendor id, product id) -> name. The K556 ships with two controllers.
PRODUCT_IDS = {
    (0x320F, 0x5000): "Redragon K556 (EVision)",
    (0x0C45, 0x5004): "Redragon K556 (SONiX)",
}
VENDOR_USAGE_PAGE = b"\x06\x1c\xff"
PACKET_SIZE = 64
REPORT_ID = 0x04
CMD_BEGIN = 0x01
CMD_END = 0x02
CMD_SET_PARAMETER = 0x06

SPEED_RANGE = (1, 6)  # UI scale, slow -> fast; mapped to firmware 5..0
BRIGHTNESS_RANGE = (1, 4)
# Firmware direction codes, verified on a 320f:5000 K556. The firmware only
# understands 0 and 1 on either axis (2 and 3, as sent by OpenRGB, fall back
# to the default): horizontal 0 = right, 1 = left; vertical 0 = down, 1 = up.
DIRECTION_CODES = {
    "lr": {"right": 0, "left": 1},
    "ud": {"down": 0, "up": 1},
}

# Mode codes verified on a K556 with the EVision controller (320f:5000); they
# match OpenRGB's generic EVision table. The SONiX revision (0c45:5004) uses a
# different table for 0x01, 0x03, 0x04, 0x07 and 0x0B
# (see syndicalt/openrgb-reddragonk556-controller).
EFFECTS: list[Effect] = [
    Effect("static", "Static", "Solid color", (0x06,), True, False, "optional"),
    Effect("breathing", "Breathing", "The color slowly pulses", (0x05,), True, True, "optional"),
    Effect("wave", "Wave", "Flowing wave of color", (0x02,), True, True, "optional", "lr"),
    Effect("wave_short", "Short wave", "Narrow wave of color", (0x01,), True, True, "optional", "lr"),
    Effect("spectrum", "Spectrum cycle", "The whole keyboard slowly cycles through colors", (0x04,), False, True, "always"),
    Effect("rain", "Rain", "Light drops falling down the columns", (0x03,), True, True, "optional"),
    Effect("blooming", "Blooming", "Every key slowly cycles its own random color", (0x0B,), False, True, "always"),
    Effect("vertical_rainbow", "Vertical rainbow", "Rainbow moving up or down", (0x0C,), False, True, "always", "ud"),
    Effect("rainbow_circle", "Rainbow circle", "Color rings spreading from the centre", (0x12,), False, True, "always"),
    Effect("hurricane", "Hurricane", "Swirl of color", (0x0D,), True, True, "optional"),
    Effect("accumulate", "Accumulate", "Keys light up one by one", (0x0E,), True, True, "optional"),
    Effect("starlight", "Starlight", "Random twinkling keys", (0x0A,), True, True, "optional"),
    Effect("starlight_slow", "Starlight (slow)", "Calmer twinkling", (0x0F,), True, True, "optional"),
    Effect("visor", "Visor", "A bar sweeping back and forth", (0x10,), True, True, "optional"),
    Effect("reactive", "Reactive", "The pressed key lights up, then fades", (0x07,), True, True, "optional"),
    Effect("ripple", "Ripple", "Ring spreading from the pressed key", (0x08,), True, True, "optional"),
    Effect("reactive_line", "Reactive line", "Line running from the pressed key", (0x09,), True, True, "optional"),
    Effect("off", "Off", "LEDs off", (0x06,), is_off=True),
]
EFFECTS_BY_KEY = {e.key: e for e in EFFECTS}


class KeyboardError(Exception):
    pass


class KeyboardNotFound(KeyboardError):
    pass


class KeyboardPermissionError(KeyboardError):
    pass


@dataclass(frozen=True)
class KeyboardInfo:
    path: str
    name: str
    product_id: int


def find_keyboards() -> list[KeyboardInfo]:
    found = []
    for node in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        try:
            uevent = (node / "device" / "uevent").read_text()
            descriptor = (node / "device" / "report_descriptor").read_bytes()
        except OSError:
            continue
        hid_id = next((l.split("=", 1)[1] for l in uevent.splitlines() if l.startswith("HID_ID=")), "")
        parts = hid_id.split(":")
        if len(parts) != 3:
            continue
        ids = (int(parts[1], 16), int(parts[2], 16))
        if ids in PRODUCT_IDS and VENDOR_USAGE_PAGE in descriptor:
            found.append(KeyboardInfo(f"/dev/{node.name}", PRODUCT_IDS[ids], ids[1]))
    return found


def _checksum(buf: bytearray) -> None:
    # OpenRGB sums the bytes as (signed) char into an unsigned short; replicate
    # it exactly since that is what is known to work with the firmware.
    total = 0
    for b in buf[3:]:
        total += b - 256 if b >= 128 else b
    total &= 0xFFFF
    buf[1] = total & 0xFF
    buf[2] = total >> 8


class RedragonKeyboard:
    def __init__(self, info: KeyboardInfo | None = None):
        if info is None:
            devices = find_keyboards()
            if not devices:
                raise KeyboardNotFound("No Redragon K556 keyboard found.")
            info = devices[0]
        self.info = info
        try:
            self._fd = os.open(info.path, os.O_RDWR)
        except PermissionError as exc:
            raise KeyboardPermissionError(
                "Permission denied on the keyboard. Reinstall the udev rule: sudo ./install-udev.sh"
            ) from exc
        except OSError as exc:
            raise KeyboardError(f"Could not open {info.path}: {exc}") from exc

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "RedragonKeyboard":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _transfer(self, command: int, parameter: int, data: bytes) -> None:
        buf = bytearray(PACKET_SIZE)
        buf[0] = REPORT_ID
        buf[3] = command
        buf[4] = len(data)
        buf[5] = parameter
        buf[8 : 8 + len(data)] = data
        _checksum(buf)
        try:
            os.write(self._fd, bytes(buf))
            # The keyboard acknowledges every packet; drain the answer.
            ready, _, _ = select.select([self._fd], [], [], 0.5)
            if ready:
                os.read(self._fd, PACKET_SIZE)
        except OSError as exc:
            raise KeyboardError(f"Keyboard communication error: {exc}") from exc

    def set_lighting(
        self,
        effect: Effect | str,
        color: tuple[int, int, int] = (255, 30, 60),
        speed: int = 3,
        brightness: int = 4,
        direction: str = "left",
        multicolor: bool = False,
    ) -> None:
        if isinstance(effect, str):
            effect = EFFECTS_BY_KEY[effect]
        r, g, b = (max(0, min(255, int(c))) for c in color)
        speed = max(SPEED_RANGE[0], min(SPEED_RANGE[1], int(speed)))
        fw_speed = SPEED_RANGE[1] - speed  # 6 -> 0 (fastest), 1 -> 5 (slowest)
        fw_brightness = 0 if effect.is_off else max(BRIGHTNESS_RANGE[0], min(BRIGHTNESS_RANGE[1], int(brightness)))
        if effect.random == "always":
            rnd = 1
        elif effect.random == "optional":
            rnd = 1 if multicolor else 0
        else:
            rnd = 0
        if effect.direction:
            codes = DIRECTION_CODES[effect.direction]
            fw_dir = codes.get(direction, max(codes.values()))  # default: left / up
        else:
            fw_dir = 0
        data = bytes([effect.code[0], fw_brightness, fw_speed, fw_dir, rnd, r, g, b])
        self._transfer(CMD_BEGIN, 0x00, b"")
        try:
            self._transfer(CMD_SET_PARAMETER, 0x00, data)
        finally:
            self._transfer(CMD_END, 0x00, b"")

    def send_raw_mode(self, code: int, color=(255, 255, 255), speed: int = 3, brightness: int = 4,
                      direction: int = 0) -> None:
        """Diagnostics: send an arbitrary mode/direction code (used to map firmware variants)."""
        data = bytes([code, brightness, speed, direction, 0, *color])
        self._transfer(CMD_BEGIN, 0x00, b"")
        try:
            self._transfer(CMD_SET_PARAMETER, 0x00, data)
        finally:
            self._transfer(CMD_END, 0x00, b"")
