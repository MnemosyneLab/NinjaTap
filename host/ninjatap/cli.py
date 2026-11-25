"""Command-line access to the phone operations."""

import argparse
import sys
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from ninjatap.agent import HEIGHT, MAX_TAPS, WIDTH, Session, save_png
from ninjatap.guide import read_guide
from ninjatap.trajectory import HOLD_DRAG_MS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ninjatap",
        description=f"Control the phone using {WIDTH}×{HEIGHT} screen coordinates.",
        epilog=(
            "Use ninjatap guide for workflows and ninjatap COMMAND --help for syntax. "
            "Set NINJATAP_URL, NINJATAP_SECRET, and NINJATAP_TLS_FINGERPRINT in the project .env or command environment."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("guide", help="Print the agent operating guide offline")

    screenshot = commands.add_parser(
        "screenshot",
        help="Save a PNG, optionally printing OCR text",
        description="Save the full screen as a PNG. Enable OCR to print text and pixel coordinates.",
    )
    screenshot.add_argument("path", type=Path, help="Output .png path")
    ocr_options = screenshot.add_mutually_exclusive_group()
    ocr_options.add_argument("--ocr", action="store_true", help="Also print OCR text and pixel coordinates")
    ocr_options.add_argument(
        "--no-ocr", dest="ocr", action="store_false", help="Skip OCR (default; legacy flag)"
    )
    screenshot.set_defaults(ocr=False)

    for name, help_text in (
        ("tap", "Default tap for buttons and cards; may land a few pixels off"),
        ("tap_exact", "Tap the exact pixel for small targets or coordinate tests"),
    ):
        tap = commands.add_parser(name, help=help_text, description=help_text)
        tap.add_argument("x", type=int)
        tap.add_argument("y", type=int)

    commands.add_parser("back", help="Send Android Back")
    commands.add_parser("home", help="Go to the Android home screen")
    commands.add_parser("lock", help="Lock the Android screen")
    commands.add_parser("unlock", help="Wake and unlock Android using the PIN saved on the phone")

    taps = commands.add_parser("taps", help=f"Tap up to {MAX_TAPS} points in one gesture")
    taps.add_argument("coordinates", metavar="COORD", type=int, nargs="+", help="Pairs of x y coordinates")

    long_press = commands.add_parser("long_press", help="Press one point for a duration")
    long_press.add_argument("x", type=int)
    long_press.add_argument("y", type=int)
    long_press.add_argument("ms", type=int, help="Duration in milliseconds")

    for name, help_text in (
        ("hold_drag", "Press, then drag without lifting"),
        ("drag", "Drag and settle at the end point"),
        ("slow_drag", "Drag slowly and lift while moving"),
        ("flick", "Flick and lift while moving quickly"),
    ):
        stroke = commands.add_parser(name, help=help_text)
        for coordinate in ("x1", "y1", "x2", "y2"):
            stroke.add_argument(coordinate, type=int)
        if name == "hold_drag":
            stroke.add_argument(
                "ms",
                type=int,
                nargs="?",
                default=HOLD_DRAG_MS,
                help=f"Initial hold in milliseconds (default: {HOLD_DRAG_MS})",
            )

    pinch = commands.add_parser("pinch", help="Pinch or spread around a center")
    for coordinate in ("cx", "cy", "start_gap", "end_gap"):
        pinch.add_argument(coordinate, type=int)

    commands.add_parser("read_clipboard", help="Print the clipboard text as-is")
    clipboard = commands.add_parser("write_clipboard", help="Replace the clipboard text")
    source = clipboard.add_mutually_exclusive_group(required=True)
    source.add_argument("text", nargs="?", help="Text to write")
    source.add_argument("--stdin", action="store_true", help="Read UTF-8 text from stdin")

    pull = commands.add_parser("pull", help="Download a file from Android shared storage")
    pull.add_argument("remote_path")
    pull.add_argument("local_path")
    push = commands.add_parser("push", help="Upload a file into Android shared storage")
    push.add_argument("local_path")
    push.add_argument("remote_path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = vars(parser.parse_args(argv))
    command = arguments.pop("command")
    if command == "guide":
        sys.stdout.write(read_guide())
        return 0
    if command == "taps":
        coordinates = arguments.pop("coordinates")
        if len(coordinates) % 2:
            parser.error("taps requires x y pairs")
        arguments["points"] = list(zip(coordinates[::2], coordinates[1::2], strict=True))

    try:
        session = Session.from_env()
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    try:
        if command == "screenshot":
            png, ocr = session.screenshot(ocr=arguments["ocr"])
            path = save_png(str(arguments["path"].absolute()), png)
            if ocr:
                print(ocr)
            print(f"Saved {path}")
        elif command == "read_clipboard":
            sys.stdout.write(session.read_clipboard())
        elif command == "write_clipboard":
            text = sys.stdin.buffer.read().decode("utf-8") if arguments["stdin"] else arguments["text"]
            print(session.write_clipboard(text))
        else:
            print(getattr(session, command)(**arguments))
    except (ToolError, OSError, ValueError) as exc:
        print(f"ninjatap: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
