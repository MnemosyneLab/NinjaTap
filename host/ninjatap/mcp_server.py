"""stdio MCP server for the local agent."""

import sys

from mcp.server.mcpserver import Image, MCPServer
from typing_extensions import TypedDict

from ninjatap.agent import Session, save_png
from ninjatap.guide import GUIDE_URI, read_guide
from ninjatap.trajectory import HOLD_DRAG_MS

INSTRUCTIONS = f"""This server drives one HONOR DNY-NX9.

Start with screenshot (PNG by default). Set ocr=true to locate visible text when
useful, and use the PNG to verify icons, images, and uncertain labels. Coordinates
refer to the latest full frame in the current orientation, with the origin at the top left.
If you receive rotation_changed, take a new screenshot before choosing coordinates.

Use tap for ordinary buttons and cards. Save tap_exact for small targets or when
you need a fixed coordinate. Use back and home for Android navigation. Wait for
the UI to settle and check a new screenshot after an action changes the screen.
Use taps only while the layout stays fixed. To enter text, write the clipboard
and paste through the app UI. Use hold_drag to select text before copying it.

Use pull and push with actual file paths under /sdcard. When transferring a saved
photo, confirm its filename in the Files app first. If an action times out, check
the screen before retrying because the phone may already have performed it.
Hand verification, permission prompts, and terms of service back to the user.
Use lock and unlock when requested. Unlock uses the PIN configured on the phone.

Read the full operating guide at {GUIDE_URI}.
"""


class _TapPoint(TypedDict):
    x: int
    y: int


def build_server(session: Session) -> MCPServer:
    server = MCPServer("ninjatap", instructions=INSTRUCTIONS)
    server.resource(
        GUIDE_URI, name="operating_guide", title="NinjaTap operating guide", mime_type="text/markdown"
    )(read_guide)

    @server.tool(structured_output=False)
    def screenshot(
        path: str = "", ocr: bool | None = None, no_ocr: bool | None = None
    ) -> list[str | Image]:
        """Capture the phone screen and read the text on it.

        Returns the full-frame PNG. With ocr=true, also returns lines formatted
        as id (center x, center y) text. Centers are full-frame pixels.
        If OCR fails, the PNG is still returned with a warning.
        path, when set, is an absolute .png path. The same frame is written there.
        Legacy no_ocr=true skips OCR; no_ocr=false enables it. Do not combine
        no_ocr with ocr.
        """
        png, text = session.screenshot(ocr=ocr, no_ocr=no_ocr)
        if path:
            saved = f"Saved {save_png(path, png)}"
            text = f"{text}\n{saved}" if text else saved
        frame = Image(data=png, format="png")
        return [text, frame] if text else [frame]

    @server.tool()
    def tap(x: int, y: int) -> str:
        """Default tap for a button or card.

        x and y are full-frame pixels. The contact may land a few pixels away.
        """
        return session.tap(x, y)

    @server.tool()
    def tap_exact(x: int, y: int) -> str:
        """Tap the exact full-frame pixel (x, y) for a small target or coordinate test."""
        return session.tap_exact(x, y)

    @server.tool()
    def back() -> str:
        """Send Android's Back key."""
        return session.back()

    @server.tool()
    def home() -> str:
        """Go to the Android home screen."""
        return session.home()

    @server.tool()
    def lock() -> str:
        """Lock the Android screen and turn the display off."""
        return session.lock()

    @server.tool()
    def unlock() -> str:
        """Wake and unlock the screen using the PIN configured in the phone app."""
        return session.unlock()

    @server.tool()
    def taps(points: list[_TapPoint]) -> str:
        """Tap several points in order, in one gesture.

        Each point has x and y in full-frame pixels. Each contact is drawn
        again and may land a few pixels off. A short gap separates the taps.
        Use this for a few keys while the keyboard stays where it is.
        At most 32 points. A whole string still goes through the clipboard.
        """
        parsed: list[tuple[int, int]] = []
        for point in points:
            parsed.append((int(point["x"]), int(point["y"])))
        return session.taps(parsed)

    @server.tool()
    def long_press(x: int, y: int, ms: int) -> str:
        """Press one point for about ms milliseconds, then lift.

        The hold stays near the requested duration. The point drifts a few pixels
        while it is down.
        """
        return session.long_press(x, y, ms)

    @server.tool()
    def hold_drag(x1: int, y1: int, x2: int, y2: int, ms: int = HOLD_DRAG_MS) -> str:
        """Press at the start, then drag to the end without lifting.

        The finger rests near (x1, y1) for about ms milliseconds, drifts a few
        pixels, curves to (x2, y2), settles, and lifts. Omit ms to rest for
        about 500ms. The end point is exact.
        The start has to sit at least 140px from the left and right edges.
        Use this to select a visible span of text. It does not copy.
        """
        return session.hold_drag(x1, y1, x2, y2, ms)

    @server.tool()
    def drag(x1: int, y1: int, x2: int, y2: int) -> str:
        """Drag from one point to another and stop on the end point.

        The path bows a few pixels off the straight line. The finger slows into
        the end, holds there, and finishes on (x2, y2).
        """
        return session.drag(x1, y1, x2, y2)

    @server.tool()
    def slow_drag(x1: int, y1: int, x2: int, y2: int) -> str:
        """Drag slowly from one point to another and lift while still moving.

        The finger keeps moving for the whole stroke and is slow at the lift,
        so the content stops where the finger lifts. The last point is (x2, y2).
        """
        return session.slow_drag(x1, y1, x2, y2)

    @server.tool()
    def flick(x1: int, y1: int, x2: int, y2: int) -> str:
        """Flick from one point to another and lift while still moving quickly.

        The stroke accelerates for about 250ms. The finger is still fast on the
        last sample, then it lifts. Use this for paging and flings. Use home
        and back for system navigation.
        """
        return session.flick(x1, y1, x2, y2)

    @server.tool()
    def pinch(cx: int, cy: int, start_gap: int, end_gap: int) -> str:
        """Pinch or spread two fingers around a center.

        start_gap and end_gap are the distances between the fingers, in pixels.
        The angle is chosen by the tool. The center drifts during the gesture.
        The gaps at the start and end are the requested ones.
        """
        return session.pinch(cx, cy, start_gap, end_gap)

    @server.tool()
    def read_clipboard() -> str:
        """Read the phone clipboard as plain text.

        Returns an empty string when the clipboard has no text. A failure is an
        error, not an empty string.
        """
        return session.read_clipboard()

    @server.tool()
    def write_clipboard(text: str) -> str:
        """Replace the phone clipboard with text.

        This does not paste into the focused field. Long-press the field, then tap paste.
        """
        return session.write_clipboard(text)

    @server.tool()
    def pull(remote_path: str, local_path: str) -> str:
        """Download a file from Android shared storage to a local file path.

        Use a file path under /sdcard, and an unused local destination.
        """
        return session.pull(remote_path, local_path)

    @server.tool()
    def push(local_path: str, remote_path: str) -> str:
        """Upload a local file to an unused Android shared-storage path.

        The parent directory on the phone must already exist.
        """
        return session.push(local_path, remote_path)

    return server


def main() -> None:
    try:
        session = Session.from_env()
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2) from None
    build_server(session).run("stdio")
