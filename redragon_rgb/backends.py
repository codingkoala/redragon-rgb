"""Uniform description of each supported device, shared by the GUI and CLI."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from . import device as mouse_drv
from . import keyboard as kb_drv
from .config import Settings, hex_to_rgb
from .effects import Effect


LED_GAMMA = 2.2


def led_rgb(hex_color: str) -> tuple[int, int, int]:
    """Screen color -> LED drive levels.

    LEDs respond roughly linearly to the PWM value, while screen colors are
    gamma-encoded, so small channel values (e.g. the red in #2f6bff) look far
    stronger on the device than on screen. Undo the gamma so they match.
    """
    return tuple(round(255 * (c / 255) ** LED_GAMMA) for c in hex_to_rgb(hex_color))  # type: ignore[return-value]


def screen_hex(rgb: tuple[int, int, int]) -> str:
    """Inverse of led_rgb: LED drive levels -> screen color."""
    from .config import rgb_to_hex
    return rgb_to_hex(tuple(round(255 * (c / 255) ** (1 / LED_GAMMA)) for c in rgb))


class BackendError(Exception):
    """Wraps driver errors. kind: "notfound" | "permission" | "other"."""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Backend:
    key: str
    title: str
    icon: str
    effects: list[Effect]
    speed_range: tuple[int, int]
    brightness_range: tuple[int, int]
    detect: Callable[[], str | None]  # device name, or None
    _apply: Callable[[Settings], None]
    _read: Callable[[Settings], Settings | None] | None = None  # current state from the device

    def read(self, base: Settings) -> Settings | None:
        """Settings as stored on the device (fields it cannot report come from `base`)."""
        if self._read is None:
            return None
        try:
            return self._read(base)
        except (mouse_drv.DeviceError, kb_drv.KeyboardError) as exc:
            raise BackendError(str(exc)) from exc

    @property
    def effects_by_key(self) -> dict[str, Effect]:
        return {e.key: e for e in self.effects}

    def apply(self, s: Settings) -> None:
        try:
            self._apply(s)
        except (mouse_drv.DevicePermissionError, kb_drv.KeyboardPermissionError) as exc:
            raise BackendError(str(exc), "permission") from exc
        except (mouse_drv.DeviceNotFound, kb_drv.KeyboardNotFound) as exc:
            raise BackendError(str(exc), "notfound") from exc
        except (mouse_drv.DeviceError, kb_drv.KeyboardError, ValueError) as exc:
            raise BackendError(str(exc)) from exc


def _detect_mouse():
    try:
        devs = mouse_drv.find_devices()
    except mouse_drv.DeviceError:
        return None
    return devs[0].name if devs else None


# Serialises every access to the mouse (lighting and DPI share one USB interface).
MOUSE_LOCK = threading.Lock()


def _apply_mouse(s: Settings) -> None:
    with MOUSE_LOCK, mouse_drv.CobraMouse() as m:
        m.set_lighting(s.effect, led_rgb(s.color), s.speed, s.brightness)


def _read_mouse(base: Settings) -> Settings | None:
    with MOUSE_LOCK, mouse_drv.CobraMouse() as m:
        lit = m.read_lighting()
    if lit.effect is None:
        return None
    s = base.copy()
    s.effect, s.speed, s.brightness = lit.effect, lit.speed, lit.brightness
    # Colorless effects may store black: keep the last chosen color. Also keep
    # it when it maps to exactly what is stored, so the round trip is lossless.
    if any(lit.color) and led_rgb(base.color) != lit.color:
        s.color = screen_hex(lit.color)
    return s


def _detect_keyboard():
    devs = kb_drv.find_keyboards()
    return devs[0].name if devs else None


def _apply_keyboard(s: Settings) -> None:
    with kb_drv.RedragonKeyboard() as k:
        if s.effect == "custom":
            k.set_custom({name: led_rgb(c) for name, c in s.keys.items()}, s.brightness)
            return
        k.set_lighting(s.effect, led_rgb(s.color), s.speed, s.brightness, s.direction, s.multicolor)


BACKENDS = {
    "mouse": Backend("mouse", "Mouse", "input-mouse-symbolic", mouse_drv.EFFECTS,
                     mouse_drv.SPEED_RANGE, mouse_drv.BRIGHTNESS_RANGE, _detect_mouse, _apply_mouse, _read_mouse),
    "keyboard": Backend("keyboard", "Keyboard", "input-keyboard-symbolic", kb_drv.EFFECTS,
                        kb_drv.SPEED_RANGE, kb_drv.BRIGHTNESS_RANGE, _detect_keyboard, _apply_keyboard),
}
