"""Persist the last applied lighting settings."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cobra-rgb"
CONFIG_FILE = CONFIG_DIR / "settings.json"


@dataclass
class Settings:
    effect: str = "static"
    color: str = "#ff1e3c"
    speed: int = 4
    brightness: int = 3

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return cls(**{k: data[k] for k in asdict(cls()) if k in data})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2))


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Colore non valido: #{value}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)
