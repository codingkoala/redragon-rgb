"""Device-independent description of a lighting effect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Effect:
    key: str
    label: str
    description: str
    code: tuple[int, ...]
    uses_color: bool = False
    uses_speed: bool = False
    # "never": always the chosen colour; "optional": user can pick multicolour;
    # "always": the effect is inherently multicolour.
    random: Literal["never", "optional", "always"] = "never"
    direction: Literal[None, "lr", "ud"] = None
    is_off: bool = False


DIRECTIONS = {
    "lr": [("left", "Verso sinistra"), ("right", "Verso destra")],
    "ud": [("up", "Verso l'alto"), ("down", "Verso il basso")],
}
