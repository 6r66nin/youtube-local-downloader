"""Offline unit tests: no network, no yt-dlp, no ffmpeg needed.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yt  # noqa: E402


class ParseTimeTests(unittest.TestCase):
    def test_plain_seconds(self):
        self.assertEqual(yt.parse_time("90"), 90)
        self.assertEqual(yt.parse_time(" 0 "), 0)

    def test_minutes_and_hours(self):
        self.assertEqual(yt.parse_time("1:30"), 90)
        self.assertEqual(yt.parse_time("1:02:30"), 3750)
        self.assertEqual(yt.parse_time("0:00"), 0)

    def test_rejects_garbage(self):
        for bad in ("", "1:2:3:4", "abc", "1:x", "1:-2", "1.5"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    yt.parse_time(bad)

    def test_rejects_out_of_range_components(self):
        with self.assertRaises(ValueError):
            yt.parse_time("1:60")


class FormatTimeTests(unittest.TestCase):
    def test_round_trip(self):
        for text, seconds in (("0:30", 30), ("1:30", 90), ("1:02:03", 3723)):
            self.assertEqual(yt.format_time(seconds), text)
            self.assertEqual(yt.parse_time(text), seconds)


class ParseRangeTests(unittest.TestCase):
    def test_closed_range(self):
        self.assertEqual(yt.parse_range("1:30-2:45"), ("1:30", "2:45"))

    def test_open_end(self):
        self.assertEqual(yt.parse_range("5:00-"), ("5:00", "inf"))
        self.assertEqual(yt.parse_range("0:00-"), ("0:00", "inf"))

    def test_missing_start_means_zero(self):
        self.assertEqual(yt.parse_range("-1:00"), ("0:00", "1:00"))

    def test_relative_start(self):
        self.assertEqual(yt.parse_range("-0:30-"), ("-0:30", "inf"))
        self.assertEqual(yt.parse_range("-0:30-0:40"), ("-0:30", "0:40"))

    def test_inverted_range_is_rejected(self):
        for bad in ("2:00-1:00", "1:00-1:00"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    yt.parse_range(bad)

    def test_invalid_input(self):
        for bad in ("", "abc", "1:00+2:00", "1:x-2:00", "1:00-2:x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    yt.parse_range(bad)


class ClipTagTests(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(yt.clip_tag("0:30", "1:00"), "clip-30-60")
        self.assertEqual(yt.clip_tag("5:00", "inf"), "clip-300-end")
        self.assertEqual(yt.clip_tag("-0:30", "inf"), "clip-r30-end")
        self.assertEqual(yt.clip_tag("1:02:30", "1:03:00"), "clip-3750-3780")

    def test_tag_is_filesystem_safe(self):
        tag = yt.clip_tag("0:30", "1:00")
        self.assertNotIn(":", tag)
        self.assertNotIn("/", tag)
        self.assertNotIn("\\", tag)


class TemplateTests(unittest.TestCase):
    def test_inserts_before_extension(self):
        template = "%(title)s [%(id)s].%(ext)s"
        self.assertEqual(
            yt.add_clip_tag(template, "clip-30-60"),
            "%(title)s [%(id)s] [clip-30-60].%(ext)s",
        )

    def test_appends_when_no_extension_marker(self):
        self.assertEqual(yt.add_clip_tag("%(title)s", "clip-30-60"), "%(title)s [clip-30-60]")


class VideoFormatTests(unittest.TestCase):
    def test_best(self):
        self.assertEqual(yt.video_format("best"), "bv*+ba/b")

    def test_capped(self):
        self.assertEqual(yt.video_format("720"), "bv*[height<=720]+ba/b[height<=720]")


class JsRuntimeTests(unittest.TestCase):
    def test_deno_wins_then_node(self):
        self.assertEqual(yt.js_runtime_flags(True, True), ["--js-runtimes", "deno"])
        self.assertEqual(yt.js_runtime_flags(False, True), ["--js-runtimes", "node"])
        self.assertEqual(yt.js_runtime_flags(False, False), [])


class CliTests(unittest.TestCase):
    def test_parser_defaults(self):
        opts = yt.build_parser().parse_args(["https://youtu.be/x"])
        self.assertEqual(opts.urls, ["https://youtu.be/x"])
        self.assertIsNone(opts.audio)
        self.assertIsNone(opts.trim)
        self.assertIsNone(opts.quality)

    def test_audio_flag_alone_means_default_format(self):
        opts = yt.build_parser().parse_args(["-a", "https://youtu.be/x"])
        self.assertEqual(opts.audio, "https://youtu.be/x")
        self.assertEqual(opts.urls, [])

    def test_audio_flag_with_format(self):
        opts = yt.build_parser().parse_args(["-a", "m4a", "https://youtu.be/x"])
        self.assertEqual(opts.audio, "m4a")
        self.assertEqual(opts.urls, ["https://youtu.be/x"])


if __name__ == "__main__":
    unittest.main()
