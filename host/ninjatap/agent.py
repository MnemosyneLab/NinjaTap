"""Phone operations an agent can call."""

import math
import os
import random
import urllib.error
from collections import ChainMap
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values
from mcp.server.mcpserver.exceptions import ToolError

from ninjatap.client import Phone, PhoneError
from ninjatap.elements import Element
from ninjatap.protocol import HEIGHT, WIDTH, Down, Move, Sleep, Step
from ninjatap.trajectory import HOLD_DRAG_MS, drag, flick, hold_drag, long_press, pinch, slow_drag, tap
from ninjatap.vision.text import read_text

MAX_TAPS = 32
TAP_GAP_MS = (40, 110)
HOLD_EDGE = 140
MAX_HOLD_MS = 10_000
MAX_PINCH_GAP = math.ceil(math.hypot(WIDTH - 1, HEIGHT - 1))


class Session:
    """One phone. Gestures are generated here and played unchanged on the device."""

    def __init__(self, phone: Phone, recognize=read_text):
        self.phone = phone
        self.recognize = recognize

    @classmethod
    def from_env(cls, environ: Mapping[str, str | None] | None = None) -> "Session":
        if environ is None:
            host_dir = Path(__file__).resolve().parents[1]
            defaults = {}
            if (host_dir / "pyproject.toml").is_file():
                defaults = dotenv_values(host_dir.parent / ".env", interpolate=False)
            environ = ChainMap(os.environ, defaults)
        url = (environ.get("NINJATAP_URL") or "").strip()
        secret = environ.get("NINJATAP_SECRET")
        fingerprint = environ.get("NINJATAP_TLS_FINGERPRINT")
        if not url or not secret or not fingerprint:
            raise ValueError("NINJATAP_URL, NINJATAP_SECRET, and NINJATAP_TLS_FINGERPRINT are required")
        return cls(Phone(url, secret, fingerprint))

    def screenshot(
        self, *, ocr: bool | None = None, no_ocr: bool | None = None
    ) -> tuple[bytes, str]:
        if ocr is not None and no_ocr is not None:
            raise ToolError("ocr and no_ocr are mutually exclusive")
        recognize = ocr if ocr is not None else no_ocr is False
        png = self._request(lambda timeout: self.phone.screencap(timeout=timeout), 30)
        if not png.startswith(b"\x89PNG"):
            raise ToolError("screencap did not return a PNG")
        if not recognize:
            return png, ""
        try:
            text = format_elements(self.recognize(png))
        except (OSError, RuntimeError, ValueError) as exc:
            text = f"Text recognition failed: {exc}"
        return png, text

    def tap(self, x: int, y: int) -> str:
        self._point(x, y)
        self._play(tap(x, y))
        return "ok"

    def tap_exact(self, x: int, y: int) -> str:
        self._point(x, y)
        self._play(tap(x, y, exact=True))
        return "ok"

    def back(self) -> str:
        return self._request(lambda timeout: self.phone.press_key("back", timeout=timeout), 20)

    def home(self) -> str:
        return self._request(lambda timeout: self.phone.press_key("home", timeout=timeout), 20)

    def lock(self) -> str:
        return self._request(lambda timeout: self.phone.set_screen_locked(True, timeout=timeout), 20)

    def unlock(self) -> str:
        return self._request(lambda timeout: self.phone.set_screen_locked(False, timeout=timeout), 25)

    def taps(self, points: list[tuple[int, int]]) -> str:
        if not points:
            raise ToolError("taps needs at least one point")
        if len(points) > MAX_TAPS:
            raise ToolError(f"taps accepts at most {MAX_TAPS} points")
        for x, y in points:
            self._point(x, y)
        rng = random.Random()
        steps: list[Step] = []
        for index, (x, y) in enumerate(points):
            if index:
                steps.append(Sleep(ms=rng.randint(TAP_GAP_MS[0], TAP_GAP_MS[1])))
            steps.extend(tap(x, y, rng=rng))
        self._play(steps)
        return "ok"

    def long_press(self, x: int, y: int, ms: int) -> str:
        self._point(x, y)
        self._hold_duration(ms)
        self._play(long_press(x, y, ms))
        return "ok"

    def hold_drag(self, x1: int, y1: int, x2: int, y2: int, ms: int = HOLD_DRAG_MS) -> str:
        self._point(x1, y1)
        self._point(x2, y2)
        if x1 < HOLD_EDGE or x1 >= WIDTH - HOLD_EDGE:
            raise ToolError(
                f"hold_drag must start at least {HOLD_EDGE} px from the left and right edges"
            )
        self._hold_duration(ms)
        self._play(hold_drag(x1, y1, x2, y2, ms=ms))
        return "ok"

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> str:
        self._point(x1, y1)
        self._point(x2, y2)
        self._play(drag(x1, y1, x2, y2))
        return "ok"

    def slow_drag(self, x1: int, y1: int, x2: int, y2: int) -> str:
        self._point(x1, y1)
        self._point(x2, y2)
        self._play(slow_drag(x1, y1, x2, y2))
        return "ok"

    def flick(self, x1: int, y1: int, x2: int, y2: int) -> str:
        self._point(x1, y1)
        self._point(x2, y2)
        self._play(flick(x1, y1, x2, y2))
        return "ok"

    def pinch(self, cx: int, cy: int, start_gap: int, end_gap: int) -> str:
        self._point(cx, cy)
        if not (1 <= start_gap <= MAX_PINCH_GAP and 1 <= end_gap <= MAX_PINCH_GAP):
            raise ToolError(f"gaps must be between 1 and {MAX_PINCH_GAP} px")
        rng = random.Random()
        for _ in range(8):
            steps = pinch(cx, cy, start_gap, end_gap, rng=rng)
            if all(
                0 <= step.x < WIDTH and 0 <= step.y < HEIGHT
                for step in steps
                if isinstance(step, (Down, Move))
            ):
                self._play(steps)
                return "ok"
        raise ToolError("pinch does not fit on the screen; move the center inward or reduce the gaps")

    def read_clipboard(self) -> str:
        return self._request(lambda timeout: self.phone.read_clipboard(timeout=timeout), 20)

    def write_clipboard(self, text: str) -> str:
        return self._request(lambda timeout: self.phone.write_clipboard(text, timeout=timeout), 20)

    def pull(self, remote_path: str, local_path: str) -> str:
        target = Path(local_path).expanduser().absolute()
        try:
            size = self.phone.pull(remote_path, target)
        except (PhoneError, OSError) as exc:
            raise ToolError(str(exc)) from exc
        return f"Downloaded {size} bytes to {target}"

    def push(self, local_path: str, remote_path: str) -> str:
        try:
            size = self.phone.push(Path(local_path).expanduser(), remote_path)
        except (PhoneError, OSError) as exc:
            raise ToolError(str(exc)) from exc
        return f"Uploaded {size} bytes to {remote_path}"

    def _play(self, steps: list[Step]) -> None:
        waits = sum(step.ms for step in steps if isinstance(step, Sleep))
        status = self._request(
            lambda timeout: self.phone.inject(steps, timeout=timeout),
            20 + waits / 1000,
        )
        if status != "ok":
            raise ToolError(status)

    def _request(self, call, timeout: float):
        try:
            return call(timeout)
        except PhoneError as exc:
            raise ToolError(str(exc)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ToolError(f"phone unreachable: {exc}") from exc

    def _point(self, x: int, y: int) -> None:
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
            raise ToolError(f"point outside the screen: {x}, {y}")

    def _hold_duration(self, ms: int) -> None:
        if not 1 <= ms <= MAX_HOLD_MS:
            raise ToolError(f"duration must be between 1 and {MAX_HOLD_MS} ms")


def save_png(path: str, png: bytes) -> str:
    target = Path(path)
    if not target.is_absolute() or target.suffix.lower() != ".png":
        raise ToolError("path must be an absolute .png path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(png)
    return str(target)


def format_elements(elements: list[Element]) -> str:
    if not elements:
        return "No text on the screen."
    return "\n".join(
        f"{element.id} ({element.cx}, {element.cy}) {element.text or ''}".rstrip()
        for element in elements
    )
