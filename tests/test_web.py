import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence import config, db, web


class WebApiTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)
        self.old_diary = config.MENTAL_DIARY_DIR
        self.old_idea = config.IDEA_INBOX_DIR
        tmp = pathlib.Path(tempfile.mkdtemp())
        config.MENTAL_DIARY_DIR = tmp
        config.IDEA_INBOX_DIR = tmp / "idea-inbox"  # 本物のVaultに書かないための差し替え

    def tearDown(self):
        config.MENTAL_DIARY_DIR = self.old_diary
        config.IDEA_INBOX_DIR = self.old_idea
        self.conn.close()

    def post(self, path, payload):
        return web.dispatch_api(self.conn, "POST", path, payload)

    def test_empty_dashboard(self):
        out = web.dispatch_api(self.conn, "GET", "/api/dashboard")
        self.assertIsNone(out["latest_checkin"])
        self.assertIsNone(out["current_task"])
        self.assertEqual(out["recent_checkins"], [])

    def test_checkin_validates_and_surfaces_crisis_support(self):
        out = self.post("/api/checkin", {
            "mood": -5,
            "sleep_hours": 4,
            "energy": 1,
            "note": "消えたい",
        })
        self.assertTrue(out["needs_support"])
        self.assertIn("0120-279-338", out["result"]["text"])
        self.assertIsNotNone(out["dashboard"]["latest_checkin"])

    def test_checkin_rejects_out_of_range_mood(self):
        with self.assertRaises(web.ApiError):
            self.post("/api/checkin", {"mood": 8})

    def test_task_add_and_complete_moves_to_next(self):
        first = self.post("/api/task", {"title": "封筒を机に出す"})
        first_id = first["dashboard"]["current_task"]["id"]
        self.post("/api/task", {"title": "書類を1枚見る"})
        done = self.post("/api/task/complete", {"task_id": first_id})
        self.assertEqual(done["dashboard"]["current_task"]["title"], "書類を1枚見る")
        achievements = self.conn.execute(
            "SELECT COUNT(*) AS n FROM achievements WHERE event_type='task_done'"
        ).fetchone()["n"]
        self.assertEqual(achievements, 1)

    def test_rhythm_accepts_partial_entry(self):
        out = self.post("/api/rhythm", {"wake": "08:30"})
        self.assertEqual(out["dashboard"]["today_rhythm"]["wake"], "08:30")

    def test_rhythm_rejects_invalid_time(self):
        with self.assertRaises(web.ApiError):
            self.post("/api/rhythm", {"wake": "28:30"})

    def test_idea_posts_and_reflects_in_dashboard(self):
        out = self.post("/api/idea", {"text": "明日これを試したい"})
        self.assertIn("result", out)
        self.assertEqual(out["dashboard"]["parked_today"], 1)

    def test_idea_requires_text(self):
        with self.assertRaises(web.ApiError):
            self.post("/api/idea", {})

    def test_idea_rejects_text_over_500_chars(self):
        with self.assertRaises(web.ApiError):
            self.post("/api/idea", {"text": "あ" * 501})

    def test_first_step_reserves_and_appears_in_dashboard(self):
        out = self.post("/api/first-step", {"step": "ファイルを開くだけ"})
        self.assertIn("result", out)
        self.assertEqual(out["dashboard"]["reserved_first_step"], "ファイルを開くだけ")

    def test_first_step_requires_step(self):
        with self.assertRaises(web.ApiError):
            self.post("/api/first-step", {})

    def test_wind_down_close_sets_day_closed(self):
        out = self.post("/api/wind-down", {"close": True})
        self.assertTrue(out["dashboard"]["day_closed"])

    def test_wind_down_without_close_returns_status(self):
        out = self.post("/api/wind-down", {})
        self.assertFalse(out["dashboard"]["day_closed"])
        self.assertIn("result", out)

    def test_low_battery_records_and_reflects_in_dashboard(self):
        out = self.post("/api/low-battery", {"water": True, "food": False})
        lb = out["dashboard"]["low_battery"]
        self.assertIsNotNone(lb)
        self.assertEqual(lb["water"], 1)
        self.assertEqual(lb["food"], 0)

    def test_low_battery_with_dont_do(self):
        out = self.post("/api/low-battery", {"dont_do": "返信しない"})
        self.assertEqual(out["dashboard"]["low_battery"]["dont_do"], "返信しない")


if __name__ == "__main__":
    unittest.main()
