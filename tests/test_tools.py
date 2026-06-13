import io
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence import config, db, tools


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)
        # メンタル日記の書き込み先をテスト用の一時ディレクトリへ差し替える
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.old_mental = config.MENTAL_DIARY_DIR
        self.old_idea = config.IDEA_INBOX_DIR
        config.MENTAL_DIARY_DIR = self.tmp
        config.IDEA_INBOX_DIR = self.tmp / "idea-inbox"

    def tearDown(self):
        config.MENTAL_DIARY_DIR = self.old_mental
        config.IDEA_INBOX_DIR = self.old_idea
        self.conn.close()

    def test_checkin_records_and_writes_diary(self):
        out = tools.log_daily_checkin(self.conn, {"mood": 2, "sleep_hours": 7, "date": "2026-06-08"})
        self.assertIn("記録しました", out["text"])
        n = self.conn.execute("SELECT COUNT(*) AS n FROM checkins").fetchone()["n"]
        self.assertEqual(n, 1)
        self.assertTrue((self.tmp / "2026-06-08.md").exists())
        self.assertNotIn("_copy_warnings", out)

    def test_checkin_crisis_note_prepends_hotline(self):
        out = tools.log_daily_checkin(self.conn, {"mood": -5, "note": "もう消えたい", "date": "2026-06-08"})
        self.assertIn("よりそいホットライン", out["text"])

    def test_checkin_med_discontinuation_nudges(self):
        out = tools.log_daily_checkin(self.conn, {"note": "薬やめたい", "date": "2026-06-08"})
        self.assertIn("主治医", out["text"])

    def test_one_thing_flow(self):
        tools.break_down_task(self.conn, {"task": "確定申告", "steps": ["書類を1枚出す", "封筒を用意する"]})
        out = tools.list_today_one_thing(self.conn, {})
        self.assertIn("書類を1枚出す", out["text"])
        out2 = tools.list_today_one_thing(self.conn, {"complete_current": True})
        self.assertIn("封筒を用意する", out2["text"])
        done = self.conn.execute(
            "SELECT COUNT(*) AS n FROM achievements WHERE event_type='task_done'").fetchone()["n"]
        self.assertEqual(done, 1)

    def test_if_then_limit_blocks_third(self):
        tools.create_if_then_plan(self.conn, {"trigger": "朝起きたら", "action": "薬を飲む"})
        tools.create_if_then_plan(self.conn, {"trigger": "昼になったら", "action": "散歩する"})
        out = tools.create_if_then_plan(self.conn, {"trigger": "夜になったら", "action": "スマホを置く"})
        self.assertTrue(out.get("needs_pruning"))

    def test_share_requires_consent_and_never_autosends(self):
        out = tools.share_summary_with_supporter(self.conn, {})
        self.assertIn("明示", out["text"])
        out2 = tools.share_summary_with_supporter(self.conn, {"consent": True, "recipient": "主治医"})
        self.assertIn("プレビュー", out2["text"])
        self.assertIn("自動送信しません", out2["text"])

    def test_route_to_crisis_support(self):
        out = tools.route_to_crisis_support(self.conn, {})
        self.assertIn("0120-279-338", out["text"])

    def test_detect_early_warning_after_logging(self):
        for d, sh in [("2026-06-06", 4.0), ("2026-06-07", 3.5)]:
            tools.log_daily_checkin(self.conn, {"mood": 2, "sleep_hours": sh, "date": d})
        out = tools.detect_early_warning(self.conn, {})
        self.assertIn("気づき", out["text"])

    def test_registry_consistent(self):
        self.assertEqual(set(tools.TOOL_SPECS), set(tools.HANDLERS))
        self.assertEqual(len(tools.TOOL_SPECS), 23)

    def test_landing_parks_idea_and_writes_inbox(self):
        out = tools.park_idea(self.conn, {"text": "Landingの画面を作る", "context": "Cadence"})
        self.assertIn("消えません", out["text"])
        self.assertTrue(pathlib.Path(out["saved_to"]).exists())
        n = self.conn.execute("SELECT COUNT(*) AS n FROM parked_ideas").fetchone()["n"]
        self.assertEqual(n, 1)

    def test_landing_reserves_only_one_first_step(self):
        target = tools._today()
        tools.reserve_first_step(self.conn, {"step": "ファイルを開く", "date": target})
        tools.reserve_first_step(self.conn, {"step": "見出しを1つ書く", "date": target})
        rows = self.conn.execute("SELECT * FROM first_steps").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["step"], "見出しを1つ書く")
        out = tools.list_today_one_thing(self.conn, {})
        self.assertTrue(out["reserved"])
        self.assertIn("見出しを1つ書く", out["text"])

    def test_landing_wind_down_and_close(self):
        tools.reserve_first_step(self.conn, {
            "step": "READMEを開く",
            "date": (tools.date.today() + tools.timedelta(days=1)).isoformat(),
        })
        out = tools.start_wind_down(self.conn, {})
        self.assertIn("READMEを開く", out["text"])
        closed = tools.start_wind_down(self.conn, {"close": True, "note": "今日はここまで"})
        self.assertTrue(closed["closed"])
        n = self.conn.execute("SELECT COUNT(*) AS n FROM day_closes").fetchone()["n"]
        self.assertEqual(n, 1)

    def test_reentry_records_reconnection_without_shaming_copy(self):
        out = tools.reenter_stalled(self.conn, {
            "target": "返信を再開する",
            "reason": "perfectionism",
        })
        self.assertNotIn("_copy_warnings", out)
        done = tools.reenter_stalled(self.conn, {"reentry_id": out["reentry_id"], "result": "partial"})
        self.assertIn("再接続", done["text"])
        n = self.conn.execute(
            "SELECT COUNT(*) AS n FROM achievements WHERE event_type='reconnection'"
        ).fetchone()["n"]
        self.assertEqual(n, 1)

    def test_low_battery_limits_visible_choices_and_routes_crisis(self):
        out = tools.low_battery_mode(self.conn, {"dont_do": "新規開発"})
        self.assertLessEqual(len(out["choices"]), 3)
        self.assertIn("今日やらないこと", out["text"])
        crisis = tools.low_battery_mode(self.conn, {"note": "消えたい"})
        self.assertIn("0120-279-338", crisis["text"])

    def test_money_fog_keeps_only_three_facts_and_one_item(self):
        out = tools.money_fog(self.conn, {
            "stopped_payments": ["カードA", "家賃"],
            "debt_total": 120000,
            "income_expected": 80000,
            "next_item": "カードAの金額を見る",
        })
        self.assertIn("3つの事実", out["text"])
        self.assertIn("120,000 円", out["text"])
        self.assertEqual(out["next_item"], "カードAの金額を見る")
        row = self.conn.execute("SELECT * FROM money_snapshots").fetchone()
        self.assertIn("カードA", row["stopped_payments"])

    def test_money_fog_rejects_negative_amount_before_saving(self):
        out = tools.money_fog(self.conn, {"debt_total": -1})
        self.assertTrue(out["needs_input"])
        n = self.conn.execute("SELECT COUNT(*) AS n FROM money_snapshots").fetchone()["n"]
        self.assertEqual(n, 0)

    def test_choose_support_mode_routes_safely(self):
        self.assertEqual(
            tools.choose_support_mode(self.conn, {"text": "お金とカード支払いが不安"})["recommended_tool"],
            "money_fog",
        )
        self.assertEqual(
            tools.choose_support_mode(self.conn, {"text": "夜なのに止まれなくてアイデアが増える"})["recommended_tool"],
            "start_wind_down",
        )
        crisis = tools.choose_support_mode(self.conn, {"text": "消えたい"})
        self.assertEqual(crisis["recommended_tool"], "route_to_crisis_support")
        self.assertIn("0120-279-338", crisis["text"])

    def test_outputs_pass_copy_guard(self):
        outs = [
            tools.log_daily_checkin(self.conn, {"mood": 1, "date": "2026-06-08"}),
            tools.track_achievement(self.conn, {}),
            tools.list_today_one_thing(self.conn, {}),
            tools.route_to_crisis_support(self.conn, {}),
            tools.build_action_plan(self.conn, {"signs": [], "show_depressive_examples": True}),
            tools.start_wind_down(self.conn, {}),
            tools.reenter_stalled(self.conn, {"target": "返信", "reason": "energy"}),
            tools.low_battery_mode(self.conn, {"dont_do": "新しいこと"}),
            tools.money_fog(self.conn, {}),
            tools.choose_support_mode(self.conn, {"text": "返信が止まっている"}),
        ]
        for o in outs:
            self.assertNotIn("_copy_warnings", o)

    # ----------------------------------------------------------------
    # 以下: 未カバーのケースを観点ごとに追加
    # ----------------------------------------------------------------

    # ---- 観点1: park_idea ----

    def test_park_idea_empty_text_returns_prompt(self):
        """空textを渡すと保存せず促し文を返す"""
        # Arrange
        args = {"text": ""}
        # Act
        out = tools.park_idea(self.conn, args)
        # Assert
        self.assertIn("一言", out["text"])
        n = self.conn.execute("SELECT COUNT(*) AS n FROM parked_ideas").fetchone()["n"]
        self.assertEqual(n, 0)

    def test_park_idea_crisis_text_prepends_hotline(self):
        """危機語「消えたい」を含むtextはホットライン前置き"""
        # Arrange
        args = {"text": "消えたいくらい疲れた"}
        # Act
        out = tools.park_idea(self.conn, args)
        # Assert
        self.assertIn("よりそいホットライン", out["text"])
        # 前置き後もアイデアの退避メッセージが続く
        self.assertIn("退避箱", out["text"])

    def test_park_idea_creates_vault_inbox_file_and_appends(self):
        """Vault INBOXファイルが作られ、2件目は追記される"""
        # Arrange & Act
        out1 = tools.park_idea(self.conn, {"text": "アイデアその1"})
        out2 = tools.park_idea(self.conn, {"text": "アイデアその2"})
        # Assert: ファイルが存在する
        p = pathlib.Path(out1["saved_to"])
        self.assertTrue(p.exists())
        content = p.read_text(encoding="utf-8")
        self.assertIn("アイデアその1", content)
        self.assertIn("アイデアその2", content)
        # DB にも2件入っている
        n = self.conn.execute("SELECT COUNT(*) AS n FROM parked_ideas").fetchone()["n"]
        self.assertEqual(n, 2)

    def test_park_idea_today_count_increments(self):
        """park_ideaするたびにtoday_countが増える"""
        # Arrange & Act
        out1 = tools.park_idea(self.conn, {"text": "1つ目"})
        out2 = tools.park_idea(self.conn, {"text": "2つ目"})
        out3 = tools.park_idea(self.conn, {"text": "3つ目"})
        # Assert
        self.assertEqual(out1["today_count"], 1)
        self.assertEqual(out2["today_count"], 2)
        self.assertEqual(out3["today_count"], 3)

    # ---- 観点2: reserve_first_step ----

    def test_reserve_first_step_overwrite_is_always_one(self):
        """同じ日付に2回予約すると常に1件で上書きされる"""
        # Arrange
        tomorrow = (tools.date.today() + tools.timedelta(days=1)).isoformat()
        # Act
        tools.reserve_first_step(self.conn, {"step": "最初の案", "date": tomorrow})
        out = tools.reserve_first_step(self.conn, {"step": "上書き案", "date": tomorrow})
        # Assert: 上書き文面
        self.assertIn("入れ替えました", out["text"])
        rows = self.conn.execute("SELECT * FROM first_steps WHERE date=?", (tomorrow,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["step"], "上書き案")

    def test_reserve_first_step_list_today_one_thing_consumes_reserved(self):
        """翌朝 list_today_one_thing が予約stepを最優先で差し出し consumed=1 になる"""
        # Arrange: 今日の日付で予約（テストは今日の日付を使う）
        today = tools._today()
        tools.reserve_first_step(self.conn, {"step": "ファイルを1行読む", "date": today})
        # 既存タスクも登録しておく（予約が勝つことを確認するため）
        tools.break_down_task(self.conn, {"task": "別のタスク", "steps": ["別ステップ"]})
        # Act
        out = tools.list_today_one_thing(self.conn, {})
        # Assert: 予約が優先
        self.assertTrue(out.get("reserved"))
        self.assertIn("ファイルを1行読む", out["text"])
        # consumed=1 になっている
        row = self.conn.execute("SELECT consumed FROM first_steps WHERE date=?", (today,)).fetchone()
        self.assertEqual(row["consumed"], 1)

    def test_reserve_first_step_reserved_beats_existing_tasks(self):
        """既存タスクがあっても予約が勝つ（2回目のlist_today_one_thingは既存タスクに戻る）"""
        # Arrange
        today = tools._today()
        tools.break_down_task(self.conn, {"task": "既存", "steps": ["既存ステップA"]})
        tools.reserve_first_step(self.conn, {"step": "予約ステップ", "date": today})
        # Act: 1回目は予約が出る
        out = tools.list_today_one_thing(self.conn, {})
        self.assertTrue(out.get("reserved"))
        self.assertIn("予約ステップ", out["text"])
        # Act: 2回目は通常タスク（予約はconsumed済み）
        out2 = tools.list_today_one_thing(self.conn, {})
        self.assertFalse(out2.get("reserved"))
        self.assertIn("既存ステップA", out2["text"])

    # ---- 観点3: start_wind_down ----

    def test_start_wind_down_status_mode_shows_parked_count_and_reservation(self):
        """状態確認モード: 退避件数・予約有無が文面に出る"""
        # Arrange
        tools.park_idea(self.conn, {"text": "退避アイデア"})
        tomorrow = (tools.date.today() + tools.timedelta(days=1)).isoformat()
        tools.reserve_first_step(self.conn, {"step": "明日の一歩", "date": tomorrow})
        # Act
        out = tools.start_wind_down(self.conn, {})
        # Assert
        self.assertIn("1 件", out["text"])          # 退避1件
        self.assertIn("明日の一歩", out["text"])    # 予約stepが出る
        self.assertEqual(out["parked_today"], 1)
        self.assertEqual(out["reserved_step"], "明日の一歩")

    def test_start_wind_down_close_records_day_close_and_achievement(self):
        """close=Trueでday_closes記録 + achievements(day_landed) が増える"""
        # Arrange & Act
        out = tools.start_wind_down(self.conn, {"close": True, "note": "テスト着地"})
        # Assert
        self.assertTrue(out["closed"])
        n_close = self.conn.execute("SELECT COUNT(*) AS n FROM day_closes").fetchone()["n"]
        self.assertEqual(n_close, 1)
        n_ach = self.conn.execute(
            "SELECT COUNT(*) AS n FROM achievements WHERE event_type='day_landed'"
        ).fetchone()["n"]
        self.assertEqual(n_ach, 1)

    def test_start_wind_down_night_accel_hint_when_high_mood_and_short_sleep(self):
        """直近checkinが mood>=2 かつ sleep<5 のとき夜の加速の気づきが出る（断定しない文面）"""
        # Arrange: mood=3, sleep=4 でチェックイン
        tools.log_daily_checkin(self.conn, {"mood": 3, "sleep_hours": 4.0})
        # Act
        out = tools.start_wind_down(self.conn, {})
        # Assert: 気づきフラグが立つ
        self.assertTrue(out["night_accel"])
        # 「かもしれません」という非断定表現が含まれる
        self.assertIn("かもしれません", out["text"])
        # 「断定ではありません」という但し書きがある（実装の仕様通り）
        self.assertIn("断定ではありません", out["text"])

    def test_start_wind_down_no_night_accel_when_mood_low(self):
        """mood<2 の場合は夜の加速ヒントが出ない"""
        # Arrange
        tools.log_daily_checkin(self.conn, {"mood": 1, "sleep_hours": 4.0})
        # Act
        out = tools.start_wind_down(self.conn, {})
        # Assert
        self.assertFalse(out["night_accel"])

    # ---- 観点4: reenter_stalled ----

    def test_reenter_stalled_no_target_returns_prompt(self):
        """target無し→促し文を返し、reentriesに保存しない"""
        # Arrange & Act
        out = tools.reenter_stalled(self.conn, {})
        # Assert
        self.assertIn("一言ください", out["text"])
        n = self.conn.execute("SELECT COUNT(*) AS n FROM reentries").fetchone()["n"]
        self.assertEqual(n, 0)

    def test_reenter_stalled_start_records_and_returns_three_principles(self):
        """開始→reentries行追加 + 3原則の文面（謝りすぎない・言い訳しない・次の一歩）"""
        # Arrange & Act
        out = tools.reenter_stalled(self.conn, {"target": "請求書を送る", "reason": "fear"})
        # Assert: DBに記録
        n = self.conn.execute("SELECT COUNT(*) AS n FROM reentries").fetchone()["n"]
        self.assertEqual(n, 1)
        # 3原則が文面に出る
        self.assertIn("謝りすぎない", out["text"])
        self.assertIn("言い訳", out["text"])
        self.assertIn("次の一歩", out["text"])
        # reentry_idが返る
        self.assertIn("reentry_id", out)

    def test_reenter_stalled_result_sent_records_reconnected_and_achievement(self):
        """result=sent → reconnected_ts記録 + achievements(reconnection)"""
        # Arrange: 開始
        start = tools.reenter_stalled(self.conn, {"target": "メールを送る"})
        # Act: 締め
        out = tools.reenter_stalled(self.conn, {"reentry_id": start["reentry_id"], "result": "sent"})
        # Assert: 再接続メッセージ
        self.assertIn("再接続", out["text"])
        # reconnected_tsが記録されている
        row = self.conn.execute(
            "SELECT reconnected_ts, result FROM reentries WHERE id=?",
            (start["reentry_id"],)
        ).fetchone()
        self.assertIsNotNone(row["reconnected_ts"])
        self.assertEqual(row["result"], "sent")
        # achievementsに reconnection が入った
        n = self.conn.execute(
            "SELECT COUNT(*) AS n FROM achievements WHERE event_type='reconnection'"
        ).fetchone()["n"]
        self.assertEqual(n, 1)

    def test_reenter_stalled_result_not_yet_no_achievement_but_not_shaming(self):
        """result=not_yet → 責めない文面、achievementsは増えない"""
        # Arrange
        start = tools.reenter_stalled(self.conn, {"target": "電話をかける"})
        # Act
        out = tools.reenter_stalled(self.conn, {"reentry_id": start["reentry_id"], "result": "not_yet"})
        # Assert: 責めない（ポジティブな前進の言及がある）
        self.assertIn("消えません", out["text"])
        # achievementsには入らない
        n = self.conn.execute(
            "SELECT COUNT(*) AS n FROM achievements WHERE event_type='reconnection'"
        ).fetchone()["n"]
        self.assertEqual(n, 0)

    # ---- 観点5: low_battery_mode / money_fog / choose_support_mode の追加分岐 ----

    def test_low_battery_mode_all_done_shows_no_choices(self):
        """水分・食事・服薬・連絡先すべて済みなら choices が空で維持できているメッセージ"""
        # Arrange: contacted も渡すと「連絡先」候補が消える（choices は最大4条件）
        # Act
        out = tools.low_battery_mode(self.conn, {
            "water": True, "food": True, "meds_taken": True, "contacted": "家族"
        })
        # Assert
        self.assertEqual(out["choices"], [])
        self.assertIn("増やさなくて大丈夫", out["text"])

    def test_low_battery_mode_upserts_same_date(self):
        """同じ日付で2回呼ぶと上書き（2行にならない）"""
        # Arrange
        today = tools._today()
        tools.low_battery_mode(self.conn, {"date": today, "water": False})
        tools.low_battery_mode(self.conn, {"date": today, "water": True})
        # Assert
        n = self.conn.execute("SELECT COUNT(*) AS n FROM low_battery_logs").fetchone()["n"]
        self.assertEqual(n, 1)
        row = self.conn.execute("SELECT water FROM low_battery_logs WHERE date=?", (today,)).fetchone()
        self.assertEqual(row["water"], 1)

    def test_money_fog_no_input_returns_guidance(self):
        """入力なし・既存レコードなしの初回は3項目の案内文を返す"""
        # Arrange & Act
        out = tools.money_fog(self.conn, {})
        # Assert: 入力案内が出る
        self.assertIn("止まっている支払い", out["text"])
        self.assertIn("借金", out["text"])
        # DBには何も保存されない
        n = self.conn.execute("SELECT COUNT(*) AS n FROM money_snapshots").fetchone()["n"]
        self.assertEqual(n, 0)

    def test_money_fog_invalid_string_debt_returns_error(self):
        """debt_totalに数字でない文字列→エラーメッセージ・保存なし"""
        # Arrange & Act
        out = tools.money_fog(self.conn, {"debt_total": "不明"})
        # Assert
        self.assertTrue(out.get("needs_input"))
        n = self.conn.execute("SELECT COUNT(*) AS n FROM money_snapshots").fetchone()["n"]
        self.assertEqual(n, 0)

    def test_choose_support_mode_empty_text_returns_prompt(self):
        """空textは保存せず、使い方の促しを返す"""
        # Arrange & Act
        out = tools.choose_support_mode(self.conn, {"text": ""})
        # Assert
        self.assertIn("一言ください", out["text"])

    def test_choose_support_mode_med_discontinuation_returns_no_tool(self):
        """減薬意図を含むテキストは recommended_tool=None を返す"""
        # Arrange & Act
        out = tools.choose_support_mode(self.conn, {"text": "薬をやめたいと思っている"})
        # Assert
        self.assertIsNone(out["recommended_tool"])
        self.assertIn("主治医", out["text"])

    def test_choose_support_mode_unknown_text_fallback_to_checkin(self):
        """パターン不一致のテキストは log_daily_checkin を勧める"""
        # Arrange & Act
        out = tools.choose_support_mode(self.conn, {"text": "特に何もない普通の日"})
        # Assert
        self.assertEqual(out["recommended_tool"], "log_daily_checkin")

    # ---- 観点6: 新ツール全件の _copy_warnings ゼロ ----

    def test_new_tools_no_copy_warnings(self):
        """新ツール7件すべてが _copy_warnings を返さない（copy_guard違反ゼロ）"""
        # Arrange: 新ツールの呼び出しに必要な前提データを用意
        today = tools._today()
        tools.log_daily_checkin(self.conn, {"mood": 1})  # start_wind_down の night_accel 用
        reentry_out = tools.reenter_stalled(self.conn, {"target": "再接続テスト"})

        new_tool_outputs = [
            # park_idea
            tools.park_idea(self.conn, {"text": "テストアイデア"}),
            # reserve_first_step
            tools.reserve_first_step(self.conn, {"step": "テスト一歩"}),
            # start_wind_down (状態確認モード)
            tools.start_wind_down(self.conn, {}),
            # start_wind_down (closeモード)
            tools.start_wind_down(self.conn, {"close": True}),
            # reenter_stalled (開始モード)
            tools.reenter_stalled(self.conn, {"target": "別の再接続"}),
            # reenter_stalled (締めモード)
            tools.reenter_stalled(self.conn, {"reentry_id": reentry_out["reentry_id"], "result": "sent"}),
            # low_battery_mode
            tools.low_battery_mode(self.conn, {"dont_do": "新規開発"}),
            # money_fog (有効入力)
            tools.money_fog(self.conn, {"debt_total": 50000, "income_expected": 100000}),
            # choose_support_mode
            tools.choose_support_mode(self.conn, {"text": "疲れて動けない"}),
        ]
        # Assert
        for out in new_tool_outputs:
            self.assertNotIn("_copy_warnings", out, msg=f"_copy_warnings found in: {out}")


class BusinessModeTest(unittest.TestCase):
    """事業所向けモード（support_plan_intake / list / export_docx / subsidy_precheck）のテスト。
    EXPORTS_DIR を tempdir に差し替えて実 Vault への書き込みを完全遮断する。
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)
        # ---- 書き込み先の隔離 ----
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        # メンタル日記 / アイデア日記（既存の隔離パターンに倣う）
        self.old_mental = config.MENTAL_DIARY_DIR
        self.old_idea = config.IDEA_INBOX_DIR
        config.MENTAL_DIARY_DIR = self.tmp
        config.IDEA_INBOX_DIR = self.tmp / "idea-inbox"
        # EXPORTS_DIR を tempdir 配下に差し替える（本物の ~/.cadence/exports に書かせない）
        self.old_exports = config.EXPORTS_DIR
        config.EXPORTS_DIR = self.tmp / "exports"

    def tearDown(self):
        config.MENTAL_DIARY_DIR = self.old_mental
        config.IDEA_INBOX_DIR = self.old_idea
        config.EXPORTS_DIR = self.old_exports
        self.conn.close()

    # ----------------------------------------------------------------
    # 観点1: support_plan_intake
    # ----------------------------------------------------------------

    def test_intake_requires_user_alias(self):
        """user_alias なしは保存せず促し文を返す"""
        # Arrange & Act
        out = tools.support_plan_intake(self.conn, {})
        # Assert
        self.assertIn("user_alias", out["text"])
        n = self.conn.execute("SELECT COUNT(*) AS n FROM support_plans").fetchone()["n"]
        self.assertEqual(n, 0)

    def test_intake_saves_plan_and_returns_plan_id(self):
        """正常系: plan_id が返り、support_plans に1行入る"""
        # Arrange
        args = {"user_alias": "A.T.", "service_type": "就労継続B", "honnin_ikou": "ゆっくり働きたい"}
        # Act
        out = tools.support_plan_intake(self.conn, args)
        # Assert: plan_id が返る
        self.assertIn("plan_id", out)
        self.assertIsInstance(out["plan_id"], int)
        # DBに1行入っている
        row = self.conn.execute("SELECT * FROM support_plans WHERE id=?", (out["plan_id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["user_alias"], "A.T.")

    def test_intake_text_contains_draft_instructions(self):
        """返りtextにサビ管・ドラフト・強み・観察可能の起草指示が含まれる"""
        # Arrange
        args = {"user_alias": "B.K.", "honnin_ikou": "仲間と作業したい"}
        # Act
        out = tools.support_plan_intake(self.conn, args)
        # Assert: 起草指示キーワード
        self.assertIn("サービス管理責任者", out["text"])
        self.assertIn("ドラフト", out["text"])
        self.assertIn("強み", out["text"])
        self.assertIn("観察可能", out["text"])

    # ----------------------------------------------------------------
    # 観点2: support_plan_list
    # ----------------------------------------------------------------

    def test_list_returns_empty_when_no_plans(self):
        """登録0件で plans=[] かつ count=0"""
        # Arrange & Act
        out = tools.support_plan_list(self.conn, {})
        # Assert
        self.assertEqual(out["plans"], [])
        self.assertEqual(out.get("count", 0), 0)

    def test_list_returns_one_after_intake_with_required_fields(self):
        """intake後は count=1 で必要フィールド(id/user_alias/status/created_ts)が返る"""
        # Arrange
        tools.support_plan_intake(self.conn, {"user_alias": "C.D."})
        # Act
        out = tools.support_plan_list(self.conn, {})
        # Assert
        self.assertEqual(out["count"], 1)
        plan = out["plans"][0]
        for field in ("id", "user_alias", "status", "created_ts"):
            self.assertIn(field, plan, msg=f"missing field: {field}")

    # ----------------------------------------------------------------
    # 観点3: support_plan_export_docx
    # ----------------------------------------------------------------

    def test_export_docx_unknown_plan_id_returns_friendly_message(self):
        """存在しない plan_id は例外でなく優しい文を返す"""
        # Arrange & Act
        out = tools.support_plan_export_docx(self.conn, {"plan_id": 9999})
        # Assert: 例外ではなく文章で返す
        self.assertIn("plan_id", out["text"].lower().replace("_", " ") + out["text"])
        # _error キーは無い（例外にならない）
        self.assertNotIn("_error", out)

    def test_export_docx_filepath_is_inside_tempdir_not_vault(self):
        """正常時の filepath が tempdir 配下（Vault 外）に作られる"""
        # Arrange
        intake = tools.support_plan_intake(self.conn, {"user_alias": "E.F."})
        plan_id = intake["plan_id"]
        # Act
        out = tools.support_plan_export_docx(self.conn, {"plan_id": plan_id})
        # Assert: filepath が tempdir 配下
        filepath = pathlib.Path(out["filepath"])
        self.assertTrue(filepath.is_relative_to(self.tmp),
                        msg=f"filepath {filepath} should be inside {self.tmp}")
        # Vault には書かれていない（出力は EXPORTS_DIR 配下に限定）
        self.assertNotIn("obsidian", str(filepath).lower())
        self.assertTrue(filepath.is_relative_to(config.EXPORTS_DIR))

    def test_export_docx_file_is_valid_zip_with_document_xml(self):
        """生成ファイルが有効な zip で word/document.xml を含む"""
        # Arrange
        import zipfile as zf
        intake = tools.support_plan_intake(self.conn, {"user_alias": "G.H."})
        # Act
        out = tools.support_plan_export_docx(self.conn, {"plan_id": intake["plan_id"]})
        filepath = out["filepath"]
        # Assert: zip として開ける
        self.assertTrue(zf.is_zipfile(filepath))
        with zf.ZipFile(filepath) as z:
            names = z.namelist()
            self.assertIn("word/document.xml", names)
            # zip 内エントリが壊れていない
            bad = z.testzip()
            self.assertIsNone(bad, msg=f"corrupt entry in zip: {bad}")

    def test_export_docx_updates_status_to_exported(self):
        """docx 生成後に support_plans.status が 'exported' に更新される"""
        # Arrange
        intake = tools.support_plan_intake(self.conn, {"user_alias": "I.J."})
        plan_id = intake["plan_id"]
        # 生成前は draft
        before = self.conn.execute("SELECT status FROM support_plans WHERE id=?", (plan_id,)).fetchone()
        self.assertEqual(before["status"], "draft")
        # Act
        tools.support_plan_export_docx(self.conn, {"plan_id": plan_id})
        # Assert
        after = self.conn.execute("SELECT status FROM support_plans WHERE id=?", (plan_id,)).fetchone()
        self.assertEqual(after["status"], "exported")

    def test_export_docx_created_date_contains_japanese_notation(self):
        """document.xml に計画作成日の日本語表記（年・月・日）が含まれる"""
        # Arrange
        import zipfile as zf
        intake = tools.support_plan_intake(self.conn, {"user_alias": "K.L."})
        # Act
        out = tools.support_plan_export_docx(self.conn, {"plan_id": intake["plan_id"]})
        # Assert: document.xml のテキストに年/月/日 が含まれる
        with zf.ZipFile(out["filepath"]) as z:
            doc_text = z.read("word/document.xml").decode("utf-8")
        self.assertIn("年", doc_text)
        self.assertIn("月", doc_text)
        self.assertIn("日", doc_text)

    # ----------------------------------------------------------------
    # 観点4: subsidy_precheck
    # ----------------------------------------------------------------

    def test_subsidy_precheck_tsuin_true_includes_jiritsushien(self):
        """通院あり(tsuin=True) で「自立支援医療」がチェックリストに含まれる"""
        # Arrange
        args = {"profile": {"tsuin": True, "working": False, "techo": "なし"}}
        # Act
        out = tools.subsidy_precheck(self.conn, args)
        # Assert
        self.assertTrue(
            any("自立支援医療" in item for item in out["checklist"]),
            msg=f"checklist: {out['checklist']}"
        )
        self.assertIn("自立支援医療", out["text"])

    def test_subsidy_precheck_no_techo_working_excludes_nenkin_includes_employment(self):
        """手帳なし＆就労中 → 年金項目なし・就労系項目あり"""
        # Arrange
        args = {"profile": {"tsuin": False, "working": True, "techo": "なし"}}
        # Act
        out = tools.subsidy_precheck(self.conn, args)
        # Assert: 障害年金は出ない（working=Trueのため）
        self.assertFalse(
            any("障害年金" in item for item in out["checklist"]),
            msg="障害年金が不要なのに含まれている"
        )
        # 就労系は出る（working=Trueのため）
        self.assertTrue(
            any("就労" in item for item in out["checklist"]),
            msg="就労系項目が含まれていない"
        )

    def test_subsidy_precheck_text_contains_caution_phrases(self):
        """返りtextに受給可否判定しない・web検索・最新等の慎重指示が含まれる"""
        # Arrange
        args = {"profile": {"tsuin": True, "working": False, "techo": "精神"}}
        # Act
        out = tools.subsidy_precheck(self.conn, args)
        # Assert: 慎重指示の表現
        self.assertIn("判定ではありません", out["text"])
        self.assertIn("web検索", out["text"])
        self.assertIn("最新", out["text"])

    def test_subsidy_precheck_saves_to_db(self):
        """subsidy_checks テーブルに保存される"""
        # Arrange
        args = {"profile": {"tsuin": True, "working": True}}
        # Act
        tools.subsidy_precheck(self.conn, args)
        # Assert
        n = self.conn.execute("SELECT COUNT(*) AS n FROM subsidy_checks").fetchone()["n"]
        self.assertEqual(n, 1)

    # ----------------------------------------------------------------
    # 観点5: copy_guard — 4ツールの返り値に _copy_warnings なし
    # ----------------------------------------------------------------

    def test_business_tools_no_copy_warnings(self):
        """事業所向け4ツールすべてが _copy_warnings を返さない"""
        # Arrange: intake で plan を1件作成
        intake_out = tools.support_plan_intake(self.conn, {"user_alias": "M.N."})

        outputs = [
            # support_plan_intake
            tools.support_plan_intake(self.conn, {"user_alias": "O.P.", "honnin_ikou": "テスト"}),
            # support_plan_list
            tools.support_plan_list(self.conn, {}),
            # support_plan_export_docx（正常系）
            tools.support_plan_export_docx(self.conn, {"plan_id": intake_out["plan_id"]}),
            # subsidy_precheck
            tools.subsidy_precheck(self.conn, {"profile": {"tsuin": True}}),
        ]
        for out in outputs:
            self.assertNotIn("_copy_warnings", out, msg=f"_copy_warnings found in: {out}")

    # ----------------------------------------------------------------
    # 観点6: docx_plan 単体テスト
    # ----------------------------------------------------------------

    def test_docx_plan_short_goals_empty_returns_bytes(self):
        """short_goals が空でもヘッダだけで例外なく bytes を返す"""
        # Arrange
        from cadence import docx_plan
        plan = {"user_alias": "Q.R.", "service_type": "就労移行", "period_months": 6}
        draft = {"short_goals": []}
        # Act
        result = docx_plan.build_support_plan_docx(plan, draft)
        # Assert: bytes を返す
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    def test_docx_plan_dangerous_chars_in_alias_xml_wellformed(self):
        """危険文字を含む user_alias でも document.xml が well-formed"""
        # Arrange
        import zipfile as zf
        import xml.dom.minidom as minidom
        from cadence import docx_plan
        plan = {
            "user_alias": "<危険&ユーザー>\"テスト'",
            "service_type": "生活介護",
            "period_months": 6,
        }
        draft = {"short_goals": []}
        # Act
        result = docx_plan.build_support_plan_docx(plan, draft)
        # Assert: zip として開ける
        self.assertTrue(zf.is_zipfile(io.BytesIO(result)))
        with zf.ZipFile(io.BytesIO(result)) as z:
            doc_bytes = z.read("word/document.xml")
        # XML が well-formed（parse で例外が出ないこと）
        try:
            minidom.parseString(doc_bytes)
        except Exception as e:
            self.fail(f"document.xml is not well-formed: {e}")


if __name__ == "__main__":
    unittest.main()
