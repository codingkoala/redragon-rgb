"""Persist the last applied lighting settings, one entry per device."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
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

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


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
    return Settings(**asdict(DEFAULTS[device]))


def save(device: str, settings: Settings) -> None:
    data = _read_all()
    data[device] = asdict(settings)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(CONFIG_FILE)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid color: #{value}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)
