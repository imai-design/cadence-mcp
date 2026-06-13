import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence import signals


class TestEarlyWarning(unittest.TestCase):
    def test_short_sleep_streak_raises_attention(self):
        checkins = [
            {"date": "2026-06-06", "mood": 1, "sleep_hours": 4.0},
            {"date": "2026-06-07", "mood": 2, "sleep_hours": 3.5},
        ]
        notices = signals.detect(checkins)
        kinds = [n["kind"] for n in notices]
        self.assertIn("short_sleep", kinds)
        short = next(n for n in notices if n["kind"] == "short_sleep")
        self.assertEqual(short["level"], "attention")

    def test_short_sleep_attaches_registered_actions(self):
        checkins = [
            {"date": "2026-06-06", "mood": 1, "sleep_hours": 4.0},
            {"date": "2026-06-07", "mood": 2, "sleep_hours": 3.5},
        ]
        signs = [{"sign_type": "manic", "text": "眠れない", "actions": ["主治医に連絡する"]}]
        notices = signals.detect(checkins, signs)
        short = next(n for n in notices if n["kind"] == "short_sleep")
        self.assertIn("主治医に連絡する", short["actions"])

    def test_mood_swing_detected(self):
        checkins = [
            {"date": "2026-06-06", "mood": -3, "sleep_hours": 7.0},
            {"date": "2026-06-07", "mood": 3, "sleep_hours": 7.0},
        ]
        kinds = [n["kind"] for n in signals.detect(checkins)]
        self.assertIn("mood_swing", kinds)

    def test_calm_data_yields_nothing(self):
        checkins = [
            {"date": "2026-06-06", "mood": 1, "sleep_hours": 7.5},
            {"date": "2026-06-07", "mood": 2, "sleep_hours": 7.0},
        ]
        self.assertEqual(signals.detect(checkins), [])

    def test_never_diagnoses(self):
        checkins = [
            {"date": "2026-06-06", "mood": 1, "sleep_hours": 4.0},
            {"date": "2026-06-07", "mood": 2, "sleep_hours": 3.0},
        ]
        for n in signals.detect(checkins):
            self.assertNotIn("あなたは躁", n["message"])
            self.assertIn(n["level"], ("info", "attention"))


if __name__ == "__main__":
    unittest.main()
