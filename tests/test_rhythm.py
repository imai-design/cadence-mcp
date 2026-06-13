import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence import rhythm


def _day(date, wake, bed):
    return {"date": date, "wake": wake, "first_contact": wake,
            "activity_start": "09:00", "dinner": "19:00", "bed": bed}


class TestToMinutes(unittest.TestCase):
    def test_parses_valid(self):
        self.assertEqual(rhythm.to_minutes("07:30"), 450)
        self.assertEqual(rhythm.to_minutes("00:00"), 0)

    def test_rejects_invalid(self):
        for bad in [None, "", "noon", "25:00", "abc"]:
            self.assertIsNone(rhythm.to_minutes(bad))


class TestCircularDiff(unittest.TestCase):
    def test_wraps_midnight(self):
        # 23:50 (1430) と 00:10 (10) は 20分差
        self.assertEqual(rhythm._circular_diff(1430, 10), 20)


class TestRegularity(unittest.TestCase):
    def test_regular_schedule_scores_high(self):
        records = [_day(f"2026-06-0{i}", "07:00", "23:00") for i in range(1, 8)]
        res = rhythm.regularity(records)
        self.assertIsNotNone(res["score_0_7"])
        self.assertGreaterEqual(res["score_0_7"], 6.5)

    def test_irregular_wake_is_flagged_shakiest(self):
        wakes = ["05:00", "11:00", "06:30", "13:00", "04:00", "12:30", "08:00"]
        records = [_day(f"2026-06-0{i+1}", wakes[i], "23:00") for i in range(7)]
        res = rhythm.regularity(records)
        self.assertIn(res["shakiest"], ("wake", "first_contact"))

    def test_insufficient_data_returns_none_score(self):
        res = rhythm.regularity([_day("2026-06-01", "07:00", "23:00")])
        self.assertIsNone(res["score_0_7"])


if __name__ == "__main__":
    unittest.main()
