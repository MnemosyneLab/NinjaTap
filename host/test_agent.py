"""Checks for the operations the MCP tools call."""

import unittest
from random import Random
from unittest.mock import patch

from mcp.server.mcpserver.exceptions import ToolError
from urllib3.response import HTTPResponse

from ninjatap.agent import HEIGHT, HOLD_EDGE, MAX_HOLD_MS, WIDTH, Session, format_elements
from ninjatap.client import Phone, PhoneError
from ninjatap.elements import Element
from ninjatap.protocol import Display, Down, Move, Sleep, Up


class AgentTest(unittest.TestCase):
    def test_screenshot_returns_the_png_and_the_text_lines(self):
        phone = _Phone(png=b"\x89PNG-screen")
        session = Session(phone, recognize=lambda png: [_element("ready", 100, 180)])
        png, text = session.screenshot(ocr=True)
        self.assertEqual(png, b"\x89PNG-screen")
        self.assertEqual(text, "1 (100, 180) ready")

    def test_a_failed_read_still_returns_the_png(self):
        phone = _Phone(png=b"\x89PNG-screen")

        def fail(png):
            raise RuntimeError("vision down")

        png, text = Session(phone, recognize=fail).screenshot(ocr=True)
        self.assertEqual(png, b"\x89PNG-screen")
        self.assertIn("vision down", text)

    def test_screenshot_reports_the_phone_readiness_status(self):
        phone = Phone("https://fixture", "test-token", "ab" * 32)
        for status in ("screen_off", "rotation"):
            with self.subTest(status=status), patch.object(
                phone, "_send", return_value=HTTPResponse(body=f'{{"status":"{status}"}}'.encode())
            ):
                with self.assertRaisesRegex(ToolError, f"^{status}$"):
                    Session(phone).screenshot()

    def test_connection_requires_a_full_fingerprint_and_https(self):
        with self.assertRaisesRegex(ValueError, "64 hex digits"):
            Phone("https://fixture", "test-token", "ab")
        with self.assertRaisesRegex(ValueError, "HTTPS origin"):
            Phone("http://fixture", "test-token", "ab" * 32)

    def test_tap_jitter_stays_on_screen(self):
        phone = _Phone()
        session = Session(phone)
        for x, y in ((0, 0), (WIDTH - 1, HEIGHT - 1)):
            with patch("ninjatap.trajectory._rng", return_value=Random(0)):
                session.tap(x, y)
            for step in phone.steps:
                if isinstance(step, (Down, Move)):
                    self.assertTrue(0 <= step.x < WIDTH and 0 <= step.y < HEIGHT)

    def test_rejects_a_pinch_that_cannot_fit_and_excessive_holds(self):
        phone = _Phone()
        session = Session(phone)
        with self.assertRaisesRegex(ToolError, "pinch does not fit"):
            session.pinch(0, 0, 300, 500)
        with self.assertRaisesRegex(ToolError, "duration"):
            session.long_press(400, 800, MAX_HOLD_MS + 1)
        with self.assertRaisesRegex(ToolError, "duration"):
            session.hold_drag(400, 800, 500, 900, MAX_HOLD_MS + 1)
        self.assertEqual(phone.calls, 0)

    def test_tap_rejects_a_point_outside_the_screen(self):
        phone = _Phone()
        with self.assertRaises(ToolError):
            Session(phone).tap(2000, 10)
        self.assertIsNone(phone.steps)

    def test_taps_plays_each_point_once_with_a_gap(self):
        phone = _Phone()
        points = [(100, 200), (180, 200), (260, 200)]
        self.assertEqual(Session(phone).taps(points), "ok")
        self.assertEqual(phone.calls, 1)
        downs = [step for step in phone.steps if isinstance(step, Down)]
        self.assertEqual(len(downs), 3)
        for down, (x, y) in zip(downs, points):
            self.assertLessEqual(abs(down.x - x), 4)
            self.assertLessEqual(abs(down.y - y), 4)
        ups = [index for index, step in enumerate(phone.steps) if isinstance(step, Up)]
        self.assertEqual(len(ups), 3)
        gap = phone.steps[ups[0] + 1]
        self.assertIsInstance(gap, Sleep)
        self.assertGreaterEqual(gap.ms, 40)
        self.assertLessEqual(gap.ms, 110)
        self.assertNotEqual(
            (downs[0].pressure, downs[0].major, downs[0].orientation),
            (downs[1].pressure, downs[1].major, downs[1].orientation),
        )

    def test_taps_rejects_an_empty_list_and_a_point_outside(self):
        phone = _Phone()
        with self.assertRaises(ToolError):
            Session(phone).taps([])
        with self.assertRaises(ToolError):
            Session(phone).taps([(10, 10), (2000, 10)])
        with self.assertRaises(ToolError):
            Session(phone).taps([(10, 10)] * 33)
        self.assertEqual(phone.calls, 0)

    def test_tap_plays_a_contact_near_the_point(self):
        phone = _Phone()
        self.assertEqual(Session(phone).tap(632, 1500), "ok")
        down = next(step for step in phone.steps if isinstance(step, Down))
        self.assertLessEqual(abs(down.x - 632), 4)
        self.assertLessEqual(abs(down.y - 1500), 4)

    def test_exact_tap_keeps_all_contacts_at_the_requested_pixel(self):
        phone = _Phone()
        self.assertEqual(Session(phone).tap_exact(632, 1500), "ok")
        positions = {(step.x, step.y) for step in phone.steps if isinstance(step, (Down, Move))}
        self.assertEqual(positions, {(632, 1500)})

    def test_landscape_touch_uses_screenshot_coordinates_and_rotation(self):
        phone = _Phone(rotation=1)
        session = Session(phone)
        session.screenshot()
        self.assertEqual(session.tap_exact(2000, 900), "ok")
        self.assertEqual(phone.injected_rotation, 1)
        self.assertEqual(
            {(step.x, step.y) for step in phone.steps if isinstance(step, (Down, Move))},
            {(2000, 900)},
        )
        with self.assertRaisesRegex(ToolError, "outside the screen"):
            session.tap_exact(900, 2000)
        phone.rotation = 3
        with self.assertRaisesRegex(ToolError, "rotation_changed"):
            session.tap_exact(2000, 900)

    def test_back_and_home_send_separate_android_keys(self):
        phone = Phone("https://fixture", "test-token", "ab" * 32)
        with patch.object(phone, "_open", return_value=b'{"status":"ok"}') as request:
            session = Session(phone)
            self.assertEqual(session.back(), "ok")
            request.assert_called_once_with("/key", b'{"key": "back"}', 20)
            request.reset_mock()
            self.assertEqual(session.home(), "ok")
            request.assert_called_once_with("/key", b'{"key": "home"}', 20)

    def test_a_phone_status_is_a_tool_error(self):
        phone = _Phone(status="screen_off")
        with self.assertRaises(ToolError) as caught:
            Session(phone).tap(10, 10)
        self.assertIn("screen_off", str(caught.exception))

    def test_screen_control_sends_no_credential(self):
        phone = Phone("https://fixture", "test-token", "ab" * 32)
        session = Session(phone)
        with patch.object(phone, "_open", return_value=b'{"status":"ok"}') as request:
            for command, timeout in (("lock", 20), ("unlock", 25)):
                self.assertEqual(getattr(session, command)(), "ok")
                request.assert_called_once_with(f"/screen/{command}", b"", timeout)
                request.reset_mock()
        with patch.object(phone, "_open", side_effect=PhoneError("screen_pin_reset_required")):
            with self.assertRaisesRegex(ToolError, "screen_pin_reset_required"):
                session.unlock()

    def test_hold_drag_is_one_contact_and_rejects_a_side_start(self):
        phone = _Phone()
        self.assertEqual(Session(phone).hold_drag(400, 800, 900, 1500), "ok")
        self.assertEqual(phone.calls, 1)
        downs = [step for step in phone.steps if isinstance(step, Down)]
        ups = [step for step in phone.steps if isinstance(step, Up)]
        self.assertEqual(len(downs), 1)
        self.assertEqual(len(ups), 1)
        self.assertEqual((downs[0].x, downs[0].y), (400, 800))
        moves = [step for step in phone.steps if not isinstance(step, (Down, Up, Sleep))]
        self.assertEqual((moves[-1].x, moves[-1].y), (900, 1500))
        self.assertEqual(Session(phone).hold_drag(HOLD_EDGE, 800, 900, 1500), "ok")
        self.assertEqual(Session(phone).hold_drag(WIDTH - HOLD_EDGE - 1, 800, 200, 1500), "ok")
        rejected = _Phone()
        session = Session(rejected)
        with self.assertRaises(ToolError):
            session.hold_drag(HOLD_EDGE - 1, 800, 900, 1500)
        with self.assertRaises(ToolError):
            session.hold_drag(WIDTH - HOLD_EDGE, 800, 900, 1500)
        with self.assertRaises(ToolError):
            session.hold_drag(400, 800, 2000, 10)
        with self.assertRaises(ToolError):
            session.hold_drag(400, 800, 900, 1500, ms=0)
        self.assertEqual(rejected.calls, 0)

    def test_long_press_drag_and_pinch_reach_the_phone(self):
        phone = _Phone()
        session = Session(phone)
        self.assertEqual(session.long_press(20, 30, 400), "ok")
        self.assertEqual(session.drag(20, 30, 80, 90), "ok")
        self.assertEqual(session.slow_drag(20, 30, 400, 900), "ok")
        self.assertEqual(session.flick(20, 30, 400, 900), "ok")
        self.assertEqual(session.pinch(400, 800, 500, 200), "ok")
        self.assertEqual(session.write_clipboard("小红书"), "ok")
        self.assertEqual(session.read_clipboard(), "小红书")
        self.assertEqual(phone.calls, 5)
        self.assertEqual(phone.clipboard, "小红书")

    def test_format_uses_ids_and_centers(self):
        text = format_elements([_element("Wi-Fi", 302, 1205)])
        self.assertEqual(text, "1 (302, 1205) Wi-Fi")


def _element(text: str, cx: int, cy: int) -> Element:
    return Element(id=1, kind="text", cx=cx, cy=cy, text=text)


class _Phone:
    def __init__(self, png=b"\x89PNG", status="ok", rotation=0):
        self.png = png
        self.status = status
        self.steps = None
        self.calls = 0
        self.clipboard = ""
        self.rotation = rotation
        self.injected_rotation = None

    def display(self, timeout=None):
        return Display(self.rotation)

    def capture(self, timeout=None):
        return self.png, self.display()

    def inject(self, steps, timeout=None, *, rotation=0):
        self.calls += 1
        self.steps = steps
        self.injected_rotation = rotation
        if self.status != "ok":
            raise PhoneError(self.status)
        return "ok" if rotation == self.rotation else "rotation_changed"

    def read_clipboard(self, timeout=None):
        if self.status != "ok":
            raise PhoneError(self.status)
        return self.clipboard

    def write_clipboard(self, text, timeout=None):
        if self.status != "ok":
            raise PhoneError(self.status)
        self.clipboard = text
        return "ok"


if __name__ == "__main__":
    unittest.main()
