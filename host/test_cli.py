"""Checks for the CLI screenshot flags without reaching a phone."""

import contextlib
import io
import unittest

from ninjatap.cli import build_parser


class CliTest(unittest.TestCase):
    def test_screenshot_ocr_is_opt_in(self):
        parser = build_parser()
        for flags, expected in (([], False), (["--ocr"], True), (["--no-ocr"], False)):
            with self.subTest(flags=flags):
                args = parser.parse_args(["screenshot", *flags, "frame.png"])
                self.assertIs(args.ocr, expected)

    def test_screenshot_ocr_flags_are_mutually_exclusive(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            build_parser().parse_args(["screenshot", "--ocr", "--no-ocr", "frame.png"])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("not allowed", stderr.getvalue())
