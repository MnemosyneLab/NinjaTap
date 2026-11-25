"""Readable strings and their boxes, in full-frame pixels."""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ninjatap.elements import Element

_SOURCE = Path(__file__).with_name("recognize.swift")
_HOST_DIR = _SOURCE.resolve().parents[2]
_CACHE_DIR = (
    _HOST_DIR / ".build"
    if (_HOST_DIR / "pyproject.toml").is_file()
    else Path.home() / "Library" / "Caches" / "ninjatap"
)
_BINARY = _CACHE_DIR / "recognize"


@dataclass(frozen=True)
class Hit:
    text: str
    x: int
    y: int
    w: int
    h: int


def read_text(png: bytes) -> list[Element]:
    """Return one element per readable string, top to bottom.

    Overlapping boxes become one element. Ids start at 1.
    """
    return elements_from_hits(_recognize(png))


def elements_from_hits(hits: list[Hit]) -> list[Element]:
    merged = _merge(list(hits))
    merged.sort(key=lambda hit: (hit.y, hit.x))
    elements = []
    for index, hit in enumerate(merged, start=1):
        elements.append(
            Element(
                id=index,
                kind="text",
                cx=hit.x + hit.w // 2,
                cy=hit.y + hit.h // 2,
                text=hit.text,
            )
        )
    return elements


def _recognize(png: bytes) -> list[Hit]:
    binary = _ensure_binary()
    with tempfile.NamedTemporaryFile(suffix=".png") as image:
        image.write(png)
        image.flush()
        result = subprocess.run(
            [str(binary), image.name],
            check=False,
            capture_output=True,
        )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(detail or "text recognition failed")
    payload = json.loads(result.stdout)
    return [
        Hit(text=item["text"], x=item["x"], y=item["y"], w=item["w"], h=item["h"])
        for item in payload
        if str(item["text"]).strip()
    ]


def _ensure_binary() -> Path:
    if _BINARY.exists() and _BINARY.stat().st_mtime >= _SOURCE.stat().st_mtime:
        return _BINARY
    _BINARY.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=_BINARY.parent) as directory:
        candidate = Path(directory) / _BINARY.name
        compiled = subprocess.run(
            ["swiftc", "-O", "-o", str(candidate), str(_SOURCE)],
            check=False,
            capture_output=True,
        )
        if compiled.returncode != 0:
            detail = compiled.stderr.decode(errors="replace").strip()
            raise RuntimeError(detail or "swiftc failed")
        candidate.replace(_BINARY)
    return _BINARY


def _merge(hits: list[Hit]) -> list[Hit]:
    changed = True
    while changed:
        changed = False
        for index, hit in enumerate(hits):
            for other in hits[index + 1 :]:
                if _overlaps(hit, other):
                    hits.remove(other)
                    hits[index] = _union(hit, other)
                    changed = True
                    break
            if changed:
                break
    return hits


def _overlaps(left: Hit, right: Hit) -> bool:
    return (
        left.x < right.x + right.w
        and right.x < left.x + left.w
        and left.y < right.y + right.h
        and right.y < left.y + left.h
    )


def _union(left: Hit, right: Hit) -> Hit:
    x = min(left.x, right.x)
    y = min(left.y, right.y)
    first, second = sorted((left, right), key=lambda hit: (hit.y, hit.x))
    return Hit(
        text=f"{first.text} {second.text}",
        x=x,
        y=y,
        w=max(left.x + left.w, right.x + right.w) - x,
        h=max(left.y + left.h, right.y + right.h) - y,
    )
