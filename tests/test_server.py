import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence import db, server


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_initialize_returns_server_info(self):
        resp = server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05"}}, self.conn)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "cadence")
        self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")

    def test_tools_list_exposes_all_tools(self):
        resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, self.conn)
        self.assertEqual(len(resp["result"]["tools"]), 23)
        for tool in resp["result"]["tools"]:
            self.assertIn("inputSchema", tool)

    def test_tools_call_returns_content(self):
        resp = server.handle(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "route_to_crisis_support", "arguments": {}}}, self.conn)
        text = resp["result"]["content"][0]["text"]
        self.assertIn("0120", text)
        self.assertFalse(resp["result"]["isError"])

    def test_notification_yields_no_response(self):
        self.assertIsNone(
            server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.conn))

    def test_unknown_method_errors(self):
        resp = server.handle({"jsonrpc": "2.0", "id": 9, "method": "foo/bar"}, self.conn)
        self.assertIn("error", resp)


if __name__ == "__main__":
    unittest.main()
