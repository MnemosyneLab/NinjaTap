"""The local process speaks MCP and publishes the phone tools."""

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver.exceptions import ToolError

from ninjatap.agent import Session
from ninjatap.cli import main as cli_main
from ninjatap.guide import GUIDE_URI
from ninjatap.mcp_server import build_server
from ninjatap.protocol import Display


class McpTest(unittest.TestCase):
    def test_mcp_resource_and_offline_cli_serve_the_same_guide(self):
        server = build_server(Session(_Phone()))
        output = StringIO()
        with redirect_stdout(output), patch.object(Session, "from_env", side_effect=AssertionError):
            self.assertEqual(cli_main(["guide"]), 0)

        async def read():
            return list(await server.read_resource(GUIDE_URI))

        resource, = anyio.run(read)
        self.assertEqual(resource.mime_type, "text/markdown")
        self.assertEqual(resource.content, output.getvalue())
        self.assertIn("# NinjaTap Agent 操作指南", resource.content)

    def test_tools_cover_the_screen_and_the_gestures(self):
        server = build_server(Session(_Phone()))

        async def listed():
            return await server.list_tools()

        names = [tool.name for tool in anyio.run(listed)]
        self.assertEqual(
            names,
            [
                "screenshot",
                "tap",
                "tap_exact",
                "back",
                "home",
                "lock",
                "unlock",
                "taps",
                "long_press",
                "hold_drag",
                "drag",
                "slow_drag",
                "flick",
                "pinch",
                "read_clipboard",
                "write_clipboard",
                "pull",
                "push",
            ],
        )

    def test_screenshot_tool_returns_text_and_a_png(self):
        server = build_server(
            Session(_Phone(), recognize=lambda png: [])
        )

        async def called():
            return await server.call_tool("screenshot", {"ocr": True})

        result = anyio.run(called)
        self.assertFalse(result.is_error)
        kinds = [block.type for block in result.content]
        self.assertEqual(kinds, ["text", "image"])
        self.assertIn("No text", result.content[0].text)
        self.assertEqual(result.content[1].mime_type, "image/png")

    def test_default_and_explicit_no_ocr_return_just_the_png(self):
        def unexpected_ocr(png):
            self.fail("OCR must not run without opt-in")

        server = build_server(Session(_Phone(), recognize=unexpected_ocr))

        async def called(args):
            return await server.call_tool("screenshot", args)

        for args in ({}, {"ocr": False}, {"no_ocr": True}):
            with self.subTest(args=args):
                result = anyio.run(called, args)
                self.assertFalse(result.is_error)
                self.assertEqual([block.type for block in result.content], ["image"])

    def test_legacy_explicit_no_ocr_false_enables_recognition(self):
        server = build_server(Session(_Phone(), recognize=lambda png: []))

        async def called():
            return await server.call_tool("screenshot", {"no_ocr": False})

        result = anyio.run(called)
        self.assertFalse(result.is_error)
        self.assertEqual([block.type for block in result.content], ["text", "image"])

    def test_opt_in_recognizer_failure_still_returns_png(self):
        def fail(png):
            raise RuntimeError("vision down")

        server = build_server(Session(_Phone(), recognize=fail))

        async def called():
            return await server.call_tool("screenshot", {"ocr": True})

        result = anyio.run(called)
        self.assertFalse(result.is_error)
        self.assertEqual([block.type for block in result.content], ["text", "image"])
        self.assertIn("vision down", result.content[0].text)

    def test_ocr_flags_are_mutually_exclusive(self):
        server = build_server(Session(_Phone(), recognize=lambda png: []))

        async def called():
            return await server.call_tool("screenshot", {"ocr": True, "no_ocr": False})

        with self.assertRaisesRegex(ToolError, "mutually exclusive"):
            anyio.run(called)

    def test_screenshot_tool_writes_an_absolute_png(self):
        server = build_server(Session(_Phone(), recognize=lambda png: []))

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "frame.png"

            async def called():
                return await server.call_tool("screenshot", {"path": str(target)})

            result = anyio.run(called)
            self.assertFalse(result.is_error)
            self.assertEqual(target.read_bytes(), b"\x89PNG\r\n\x1a\n")
            self.assertIn(str(target), result.content[0].text)

    def test_screenshot_tool_rejects_a_relative_path(self):
        server = build_server(Session(_Phone(), recognize=lambda png: []))

        async def called():
            return await server.call_tool("screenshot", {"path": "frame.png"})

        with self.assertRaises(ToolError) as caught:
            anyio.run(called)
        self.assertIn("absolute", str(caught.exception))

    def test_taps_tool_accepts_a_list_of_points(self):
        phone = _Phone()
        server = build_server(Session(phone, recognize=lambda png: []))

        async def called():
            return await server.call_tool(
                "taps",
                {"points": [{"x": 100, "y": 200}, {"x": 180, "y": 220}]},
            )

        result = anyio.run(called)
        self.assertFalse(result.is_error)
        self.assertEqual(result.content[0].text, "ok")
        self.assertEqual(phone.calls, 1)

    def test_hold_drag_tool_plays_one_stroke(self):
        phone = _Phone()
        server = build_server(Session(phone, recognize=lambda png: []))

        async def called():
            return await server.call_tool(
                "hold_drag",
                {"x1": 400, "y1": 800, "x2": 900, "y2": 1500, "ms": 900},
            )

        result = anyio.run(called)
        self.assertFalse(result.is_error)
        self.assertEqual(result.content[0].text, "ok")
        self.assertEqual(phone.calls, 1)

    def test_tap_tool_reports_a_phone_failure(self):
        server = build_server(Session(_Phone(status="unauthorized")))

        async def called():
            return await server.call_tool("tap", {"x": 10, "y": 10})

        with self.assertRaises(ToolError) as caught:
            anyio.run(called)
        self.assertIn("unauthorized", str(caught.exception))

    def test_stdio_server_lists_the_same_tools(self):
        import sys

        host = os.path.dirname(os.path.abspath(__file__))

        async def listed():
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "ninjatap"],
                cwd=host,
                env={
                    "NINJATAP_URL": "https://127.0.0.1:9",
                    "NINJATAP_SECRET": "test-token",
                    "NINJATAP_TLS_FINGERPRINT": "ab" * 32,
                    "PATH": os.environ.get("PATH", ""),
                },
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [tool.name for tool in result.tools]

        names = anyio.run(listed)
        self.assertEqual(
            names,
            [
                "screenshot",
                "tap",
                "tap_exact",
                "back",
                "home",
                "lock",
                "unlock",
                "taps",
                "long_press",
                "hold_drag",
                "drag",
                "slow_drag",
                "flick",
                "pinch",
                "read_clipboard",
                "write_clipboard",
                "pull",
                "push",
            ],
        )


class _Phone:
    def __init__(self, status="ok"):
        self.status = status
        self.calls = 0

    def display(self, timeout=None):
        return Display()

    def capture(self, timeout=None):
        return b"\x89PNG\r\n\x1a\n", self.display()

    def inject(self, steps, timeout=None, *, rotation=0):
        self.calls += 1
        if self.status != "ok":
            from ninjatap.client import PhoneError

            raise PhoneError(self.status)
        return self.status


if __name__ == "__main__":
    unittest.main()
