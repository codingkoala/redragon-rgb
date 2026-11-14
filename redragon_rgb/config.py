"""Persist the last applied lighting settings, one entry per device."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "redragon-rgb"
CONFIG_FILE = CONFIG_DIR / "settings.json"


@dataclass
class Settings:
    effect: str = "static"
    color: str = "#ff1e3c"
    speed: int = 4
    brightness: int = 3
    direction: str = "left"
    multicolor: bool = False
    keys: dict[str, str] = field(default_factory=dict)  # per-key colors (custom effect)

    def copy(self) -> "Settings":
        return replace(self, keys=dict(self.keys))

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        names = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in data.items() if k in names})
        if not isinstance(s.keys, dict):
            s.keys = {}
        return s


DEFAULTS = {
    "mouse": Settings(),
    "keyboard": Settings(speed=3, brightness=4),
}


def _read_all() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if "effect" in data:  # v0.1 file: flat mouse settings
        data = {"mouse": data}
    return data


def load(device: str) -> Settings:
    data = _read_all().get(device)
    if isinstance(data, dict):
        try:
            return Settings.from_dict(data)
        except TypeError:
            pass
    return DEFAULTS[device].copy()


def save(device: str, settings: Settings) -> None:
    data = _read_all()
    data[device] = asdict(settings)
    _write_all(data)


def _write_all(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(CONFIG_FILE)


Balance = tuple[float, float, float]
NEUTRAL: Balance = (1.0, 1.0, 1.0)


def load_balance(device: str) -> Balance:
    """Per-channel LED gains (0.3-1.0) that make white look white on `device`."""
    try:
        r, g, b = (max(0.3, min(1.0, float(v))) for v in _read_all()["white_balance"][device])
        return (r, g, b)
    except (KeyError, TypeError, ValueError):
        return NEUTRAL


def save_balance(device: str, balance: Balance) -> None:
    data = _read_all()
    wb = data.get("white_balance")
    if not isinstance(wb, dict):
        wb = {}
    wb[device] = [round(max(0.3, min(1.0, v)), 3) for v in balance]
    data["white_balance"] = wb
    _write_all(data)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid color: #{value}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)
