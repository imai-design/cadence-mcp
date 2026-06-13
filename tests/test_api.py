import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence import api, config, db


class AiApiTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)
        self.old_diary = config.MENTAL_DIARY_DIR
        config.MENTAL_DIARY_DIR = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        config.MENTAL_DIARY_DIR = self.old_diary
        self.conn.close()

    def test_health(self):
        out = api.dispatch_api(self.conn, "GET", "/health")
        self.assertTrue(out["ok"])
        self.assertEqual(out["service"], "cadence-api")

    def test_tool_catalog_formats(self):
        mcp = api.dispatch_api(self.conn, "GET", "/v1/tools", query={"format": ["mcp"]})
        openai = api.dispatch_api(self.conn, "GET", "/v1/tools", query={"format": ["openai"]})
        anthropic = api.dispatch_api(self.conn, "GET", "/v1/tools", query={"format": ["anthropic"]})
        self.assertEqual(len(mcp["tools"]), 23)
        self.assertEqual(openai["tools"][0]["type"], "function")
        self.assertIn("input_schema", anthropic["tools"][0])

    def test_call_tool_accepts_arguments_wrapper(self):
        out = api.dispatch_api(self.conn, "POST", "/v1/tools/log_daily_checkin/call", {
            "arguments": {"mood": 1, "sleep_hours": 7, "note": "落ち着いている"}
        })
        self.assertFalse(out["is_error"])
        self.assertIn("記録しました", out["content"][0]["text"])
        n = self.conn.execute("SELECT COUNT(*) AS n FROM checkins").fetchone()["n"]
        self.assertEqual(n, 1)

    def test_call_tool_surfaces_crisis_support(self):
        out = api.dispatch_api(self.conn, "POST", "/v1/tools/log_daily_checkin/call", {
            "arguments": {"mood": -5, "note": "消えたい"}
        })
        self.assertIn("0120-279-338", out["content"][0]["text"])

    def test_unknown_tool_raises_404(self):
        with self.assertRaises(api.ApiError) as ctx:
            api.dispatch_api(self.conn, "POST", "/v1/tools/nope/call", {"arguments": {}})
        self.assertEqual(ctx.exception.status, 404)

    def test_mcp_http_bridge_lists_tools(self):
        out = api.dispatch_api(self.conn, "POST", "/v1/mcp", {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        })
        self.assertEqual(len(out["result"]["tools"]), 23)

    def test_new_app_tools_are_exposed_to_other_ai(self):
        out = api.dispatch_api(self.conn, "GET", "/v1/tools", query={"format": ["openai"]})
        names = {item["function"]["name"] for item in out["tools"]}
        self.assertTrue({
            "park_idea", "reserve_first_step", "start_wind_down", "reenter_stalled",
            "low_battery_mode", "money_fog",
            "choose_support_mode",
        }.issubset(names))

    def test_state_summary_exposes_continuation_without_money_amounts(self):
        api.dispatch_api(self.conn, "POST", "/v1/tools/reserve_first_step/call", {
            "arguments": {"step": "READMEを開く", "date": "2099-01-01"}
        })
        api.dispatch_api(self.conn, "POST", "/v1/tools/money_fog/call", {
            "arguments": {"debt_total": 100000, "next_item": "残高を見る"}
        })
        out = api.dispatch_api(self.conn, "GET", "/v1/state/summary")
        self.assertEqual(out["landing"]["reserved_first_step"]["step"], "READMEを開く")
        self.assertEqual(out["money_fog"]["next_item"], "残高を見る")
        self.assertNotIn("debt_total", out["money_fog"])

    def test_openapi_spec_advertises_tool_endpoint(self):
        out = api.dispatch_api(self.conn, "GET", "/v1/openapi.json", base_url="http://localhost:8787")
        self.assertIn("/v1/tools/{tool_name}/call", out["paths"])
        self.assertIn("x-cadence-tools", out)

    def test_authorization_helper(self):
        class Headers(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        self.assertTrue(api._is_authorized(Headers({"X-Cadence-Token": "abc"}), "abc"))
        self.assertTrue(api._is_authorized(Headers({"Authorization": "Bearer abc"}), "abc"))
        self.assertFalse(api._is_authorized(Headers({"X-Cadence-Token": "wrong"}), "abc"))


if __name__ == "__main__":
    unittest.main()
