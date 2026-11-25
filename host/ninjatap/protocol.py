"""Sequence JSON shared with the phone player."""

from dataclasses import asdict, dataclass
from typing import Any, Literal

WIDTH = 1264
HEIGHT = 2736


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
    "no_device",
    "closed",
    "unauthorized",
    "contact",
]


def sequence_body(steps: list[Step]) -> dict[str, Any]:
    return {"sequence": [asdict(step) for step in steps]}
