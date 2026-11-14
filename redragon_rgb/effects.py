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
    # "never": always the chosen color; "optional": user can pick multicolor;
    # "always": the effect is inherently multicolor.
    random: Literal["never", "optional", "always"] = "never"
    direction: Literal[None, "lr", "ud"] = None
    is_off: bool = False


DIRECTIONS = {
    "lr": [("left", "Left"), ("right", "Right")],
    "ud": [("up", "Up"), ("down", "Down")],
}
