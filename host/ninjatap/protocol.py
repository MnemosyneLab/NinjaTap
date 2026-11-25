"""Sequence JSON shared with the phone player."""

from dataclasses import asdict, dataclass
from typing import Any, Literal

WIDTH = 1264
HEIGHT = 2736


@dataclass(frozen=True)
class Display:
    rotation: int = 0

    @property
    def size(self) -> tuple[int, int]:
        return (HEIGHT, WIDTH) if self.rotation in (1, 3) else (WIDTH, HEIGHT)

    def contains(self, x: int, y: int) -> bool:
        width, height = self.size
        return 0 <= x < width and 0 <= y < height


@dataclass(frozen=True)
class Down:
    x: int
    y: int
    id: int
    pressure: int
    major: int
    minor: int
    orientation: int
    action: Literal["down"] = "down"


@dataclass(frozen=True)
class Move:
    x: int
    y: int
    id: int
    pressure: int
    major: int
    minor: int
    orientation: int
    action: Literal["move"] = "move"


@dataclass(frozen=True)
class Up:
    id: int
    action: Literal["up"] = "up"


@dataclass(frozen=True)
class Sleep:
    ms: int
    action: Literal["sleep"] = "sleep"


Step = Down | Move | Up | Sleep

Status = Literal[
    "ok",
    "screen_off",
    "rotation",
    "rotation_changed",
    "no_device",
    "closed",
    "unauthorized",
    "contact",
]


def sequence_body(steps: list[Step], rotation: int = 0) -> dict[str, Any]:
    return {"rotation": rotation, "sequence": [asdict(step) for step in steps]}
