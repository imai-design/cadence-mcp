import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence import reminders


def _kinds(nudges):
    return {n["kind"] for n in nudges}


class TestTypicalAnchor(unittest.TestCase):
    def test_returns_median_minutes(self):
        records = [
            {"date": "2026-06-10", "wake": "07:00", "bed": "23:00"},
            {"date": "2026-06-11", "wake": "07:30", "bed": "23:30"},
            {"date": "2026-06-12", "wake": "08:00", "bed": "00:00"},
        ]
        self.assertEqual(reminders.typical_anchor_min(records, "wake"), 7 * 60 + 30)

    def test_none_when_fewer_than_two_records(self):
        records = [{"date": "2026-06-10", "wake": "07:00"}]
        self.assertIsNone(reminders.typical_anchor_min(records, "wake"))

    def test_ignores_missing_and_invalid_values(self):
        records = [
            {"date": "2026-06-10", "wake": None},
            {"date": "2026-06-11", "wake": "bad"},
            {"date": "2026-06-12", "wake": "06:00"},
        ]
        # 有効値が1つだけ → None
        self.assertIsNone(reminders.typical_anchor_min(records, "wake"))


class TestForwardCircular(unittest.TestCase):
    def test_wraps_over_midnight(self):
        # 23:30 (1410) から 00:00 (0) へは 30分先
        self.assertEqual(reminders._forward(1410, 0), 30)
        # 00:00 から 23:30 へは 1410分先
        self.assertEqual(reminders._forward(0, 1410), 1410)


class TestMorningCheckin(unittest.TestCase):
    def test_fires_near_wake_when_no_checkin(self):
        nudges = reminders.due_nudges(
            now_min=7 * 60 + 30, typical_wake_min=7 * 60, typical_bed_min=23 * 60,
            has_checkin_today=False)
        self.assertIn("morning_checkin", _kinds(nudges))

    def test_silent_when_already_checked_in(self):
        nudges = reminders.due_nudges(
            now_min=7 * 60 + 30, typical_wake_min=7 * 60, typical_bed_min=23 * 60,
            has_checkin_today=True)
        self.assertNotIn("morning_checkin", _kinds(nudges))

    def test_silent_outside_morning_window(self):
        # 起床 07:00 から 6時間後の 13:00 は朝の窓(180分)の外
        nudges = reminders.due_nudges(
            now_min=13 * 60, typical_wake_min=7 * 60, typical_bed_min=23 * 60,
            has_checkin_today=False)
        self.assertNotIn("morning_checkin", _kinds(nudges))

    def test_silent_when_no_typical_wake(self):
        nudges = reminders.due_nudges(
            now_min=7 * 60 + 30, typical_wake_min=None, typical_bed_min=23 * 60,
            has_checkin_today=False)
        self.assertNotIn("morning_checkin", _kinds(nudges))


class TestReservedStep(unittest.TestCase):
    def test_fires_during_day_when_reserved(self):
        nudges = reminders.due_nudges(
            now_min=10 * 60, typical_wake_min=7 * 60, typical_bed_min=23 * 60,
            reserved_step="READMEを開く")
        reserved = [n for n in nudges if n["kind"] == "reserved_step"]
        self.assertEqual(len(reserved), 1)
        self.assertIn("READMEを開く", reserved[0]["text"])

    def test_not_pushed_right_before_bed(self):
        # 22:30 は就寝 23:00 の手前(90分以内) → 急かさない
        nudges = reminders.due_nudges(
            now_min=22 * 60 + 30, typical_wake_min=7 * 60, typical_bed_min=23 * 60,
            reserved_step="READMEを開く")
        self.assertNotIn("reserved_step", _kinds(nudges))


class TestEveningWindDown(unittest.TestCase):
    def test_fires_when_approaching_bed(self):
        nudges = reminders.due_nudges(
            now_min=22 * 60 + 30, typical_wake_min=7 * 60, typical_bed_min=23 * 60)
        self.assertIn("evening_winddown", _kinds(nudges))

    def test_wraps_over_midnight_bed(self):
        # 就寝 00:00、いま 23:40 → 手前20分 → 出る
        nudges = reminders.due_nudges(
            now_min=23 * 60 + 40, typical_wake_min=7 * 60, typical_bed_min=0)
        self.assertIn("evening_winddown", _kinds(nudges))

    def test_silent_when_day_already_closed(self):
        nudges = reminders.due_nudges(
            now_min=22 * 60 + 30, typical_wake_min=7 * 60, typical_bed_min=23 * 60,
            day_closed=True)
        self.assertNotIn("evening_winddown", _kinds(nudges))

    def test_acceleration_adds_rest_hint_and_attention_level(self):
        nudges = reminders.due_nudges(
            now_min=22 * 60 + 30, typical_wake_min=7 * 60, typical_bed_min=23 * 60,
            acceleration=True)
        evening = [n for n in nudges if n["kind"] == "evening_winddown"][0]
        self.assertEqual(evening["level"], "attention")
        self.assertIn("退避箱", evening["text"])
        self.assertIn("断定ではありません", evening["text"])


class TestEarlyWarningAggregation(unittest.TestCase):
    def test_aggregates_to_single_nudge_with_remainder_count(self):
        notices = [
            {"kind": "short_sleep", "level": "attention", "message": "睡眠が短め"},
            {"kind": "mood_swing", "level": "info", "message": "気分の振れ幅"},
        ]
        nudges = reminders.due_nudges(now_min=15 * 60, early_notices=notices)
        early = [n for n in nudges if n["kind"] == "early_warning"]
        self.assertEqual(len(early), 1)  # 連投しない＝1件に集約
        # attention を先頭に持ち上げる
        self.assertIn("睡眠が短め", early[0]["text"])
        self.assertEqual(early[0]["level"], "attention")
        # 残り1件があることを伝える
        self.assertIn("1 件", early[0]["text"])


class TestSilence(unittest.TestCase):
    def test_no_nudges_when_nothing_applies(self):
        # 真昼・記録済み・予約なし・気づきなし → 何も言わない
        nudges = reminders.due_nudges(
            now_min=14 * 60, typical_wake_min=7 * 60, typical_bed_min=23 * 60,
            has_checkin_today=True)
        self.assertEqual(nudges, [])


if __name__ == "__main__":
    unittest.main()
