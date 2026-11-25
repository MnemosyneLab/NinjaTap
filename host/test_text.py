"""Checks for text elements and one tap from an element id."""

import unittest

from ninjatap.elements import ElementList, UnknownElement
from ninjatap.loop import once
from ninjatap.protocol import Down
from ninjatap.trajectory import TAP_JITTER
from ninjatap.vision.text import Hit, elements_from_hits


class TextTest(unittest.TestCase):
    def test_overlapping_boxes_become_one_element(self):
        elements = elements_from_hits(
            [
                Hit("logging", 48, 90, 180, 50),
                Hit("pressure", 200, 100, 160, 40),
                Hit("ready", 48, 160, 120, 40),
            ]
        )
        self.assertEqual([element.text for element in elements], ["logging pressure", "ready"])
        self.assertEqual([element.id for element in elements], [1, 2])
        self.assertEqual(elements[0].kind, "text")
        self.assertEqual(elements[1].cy, 180)

    def test_once_taps_the_center_and_returns_the_next_screenshot(self):
        elements = ElementList(elements_from_hits([Hit("ready", 40, 160, 120, 40)]))
        phone = _Phone()
        self.assertEqual(once(phone, elements, 1), b"after")
        down = next(step for step in phone.steps if isinstance(step, Down))
        self.assertLessEqual(abs(down.x - 100), TAP_JITTER)
        self.assertLessEqual(abs(down.y - 180), TAP_JITTER)

    def test_an_unknown_id_is_not_tapped(self):
        elements = ElementList(elements_from_hits([Hit("ready", 40, 160, 120, 40)]))
        phone = _Phone()
        with self.assertRaises(UnknownElement):
            once(phone, elements, 9)
        self.assertIsNone(phone.steps)


class _Phone:
    def __init__(self):
        self.steps = None

    def inject(self, steps):
        self.steps = steps
        return "ok"

    def screencap(self):
        return b"after"


if __name__ == "__main__":
    unittest.main()
