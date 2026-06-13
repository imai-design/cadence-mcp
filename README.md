# Cadence MCP

ADHD and bipolar disorder daily-rhythm support — 23 tools, zero dependencies, Python 3.9+.

ADHD・双極性障害のための生活リズム支援 MCP サーバー。Claude に話しかけるだけで使えます。

---

> [!WARNING]
> **これは医療機器でも診断ツールでもありません。**
> 気づきと習慣づくりの補助であって、主治医・薬・専門的な支援の代わりにはなりません。
> つらいときは、いつでも下の窓口へ連絡してください。
>
> - よりそいホットライン: **0120-279-338**（24時間・無料）
> - #いのちSOS: **0120-061-338**（24時間・無料）
> - 自殺予防いのちの電話: **0120-783-556**（毎日 16:00〜21:00・無料）

---

## なぜこれが効くのか

エビデンスに基づく中核だけに絞っています（思いつきの機能は入れていません）。

| 効く習慣 | 対象 | Cadence の支え方 |
|---|---|---|
| 社会リズム（起床〜就寝の5定点）を一定に保つ | 双極 | `log_social_rhythm` / `track_rhythm_regularity` |
| 睡眠を固定し、短い睡眠の連続を避ける | 双極 | `detect_early_warning`（短睡眠の連続に気づく） |
| 早期警告サインと対処を"本人の言葉で"持つ | 双極 | `build_action_plan` / `detect_early_warning` |
| 気分・睡眠の超軽量セルフモニタリング（1日30秒） | 両方 | `log_daily_checkin` |
| 大きなタスクを割って「今やる1個」だけ見る | ADHD | `break_down_task` / `list_today_one_thing` |
| if-then（実行意図）で行動をトリガーに紐づける | 両方 | `create_if_then_plan` |
| 時間を見える化（タイムボックス） | ADHD | `start_focus_timer` |
| 達成を採点せず可視化し、自分に優しく振り返る | 両方 | `track_achievement` |
| 信頼できる人とゆるく共有する | 両方 | `share_summary_with_supporter`（同意必須・自動送信なし） |
| 危機のときは専門窓口へ橋渡し | — | `route_to_crisis_support`（全ツールの安全ハブ） |

設計の流れ: **記録 → 気づき → 行動の足場 → 共有 → 安全ハブ**。
すべてのツールは、危機を検知したら `route_to_crisis_support`（窓口）へ合流します。

---

## インストール

依存パッケージはゼロです。Python 3.9 以上があれば動きます。

```bash
git clone https://github.com/imai-design/cadence-mcp.git
cd cadence-mcp
python3 run.py   # 動作確認
```

`pip install` は不要です。標準ライブラリのみで動作します。

---

## Claude Code への登録

```bash
claude mcp add cadence -- python3 /path/to/cadence-mcp/run.py
```

追加後、Claude Code を開き直すか `/mcp` で接続を確認してください。

### Smithery 経由でのインストール

[Smithery](https://smithery.ai/) に掲載されています。Smithery の UI から検索・インストールするか、
次のコマンドで追加できます。

```bash
npx -y @smithery/cli install cadence-mcp --client claude
```

---

## Vault ミラーの有効化（任意）

環境変数 `CADENCE_VAULT_ROOT` に Obsidian などの Markdown Vault のパスを指定すると、
気分ログが `YYYY-MM-DD.md` に追記されます。指定しない場合はローカル DB のみに保存されます。

```bash
CADENCE_VAULT_ROOT="/path/to/your/vault" python3 run.py
```

Claude Code の設定に追加する場合:

```json
{
  "mcpServers": {
    "cadence": {
      "command": "python3",
      "args": ["/path/to/cadence-mcp/run.py"],
      "env": {
        "CADENCE_VAULT_ROOT": "/path/to/your/vault"
      }
    }
  }
}
```

---

## 使い方（Claude にこう言うだけ）

繋いだあとは、自然な言葉で大丈夫です。

- 「今日の気分3、6時間寝た、薬は飲んだ、で記録して」 → `log_daily_checkin`
- 「起きたの8時、寝るの0時でリズム登録して」 → `log_social_rhythm`
- 「最近リズムどう?」 → `track_rhythm_regularity`
- 「確定申告、でかすぎて動けない。割って」 → `break_down_task` → `list_today_one_thing`
- 「今やることだけ見せて」 → `list_today_one_thing`
- 「終わった、次」 → `list_today_one_thing(complete_current)`

入力は1日30秒・5項目までが目安です。完璧に記録しなくていいし、休んでも大丈夫です。

---

## ツール一覧（23ツール）

### 個人向け

| ツール | 説明 |
|---|---|
| `choose_support_mode` | 相談文から使えそうな道具を安全優先で案内する入口 |
| `log_daily_checkin` | 気分・睡眠・エネルギー・服薬・一言を記録（1日30秒） |
| `log_social_rhythm` | 起床〜就寝の5定点アンカーを記録（IPSRT準拠） |
| `track_rhythm_regularity` | リズムの規則性を確認し、乱れを早期検知 |
| `build_action_plan` | 本人の言葉で早期警告サインと対処を作る |
| `detect_early_warning` | 短睡眠の連続など躁・鬱の初期サインを検出 |
| `break_down_task` | 大きなタスクを小さく割る |
| `list_today_one_thing` | 今日やる1個だけを表示・完了・次へ |
| `create_if_then_plan` | if-then形式で行動をトリガーに紐づける |
| `start_focus_timer` | 5/15/25分のタイムボックスタイマー |
| `track_achievement` | 達成を採点なしで記録・振り返る |
| `share_summary_with_supporter` | 信頼できる人と記録をゆるく共有（同意必須・自動送信なし） |
| `route_to_crisis_support` | 危機のサインを取りこぼさず専門窓口へ橋渡し（全ツールの安全ハブ） |
| `park_idea` | 夜の思いつきを失わず明日に置いておく（Landing） |
| `reserve_first_step` | 明日の入口を1つだけ作る（Landing） |
| `start_wind_down` | 今日を閉じる（Landing） |
| `reenter_stalled` | 止まった返信・請求・公開へ、完了ではなく再接続から戻る（Re-entry） |
| `low_battery_mode` | 谷の日の生活維持を最大3択までに減らす（Low Battery） |
| `money_fog` | お金の不安を3つの事実と今触る1項目へ分ける（Money Fog） |

### 事業所向け（障害福祉）

| ツール | 説明 |
|---|---|
| `support_plan_intake` | アセスメント登録と個別支援計画の骨子生成（サビ管確認前提） |
| `support_plan_list` | 起草済み支援計画の一覧 |
| `support_plan_export_docx` | 計画を Word 形式で出力（A4・サビ管承認欄付き） |
| `subsidy_precheck` | 現況から確認すべき福祉制度カテゴリをチェックリスト表示（受給可否は判定しない） |

---

## Cadence Now（ローカル画面）

会話を開く余力がない日でも使える、依存ゼロのローカル PWA です。

```bash
python3 run_web.py
```

`http://127.0.0.1:8765` をブラウザで開きます。

---

## HTTP API / 他AI連携

```bash
python3 run_api.py
```

主なエンドポイント:

- `GET /v1/tools` — MCP 互換のツール定義
- `GET /v1/tools?format=openai` — OpenAI function calling 形式
- `GET /v1/tools?format=anthropic` — Anthropic tools 形式
- `POST /v1/tools/{tool_name}/call` — ツール実行
- `GET /v1/openapi.json` — GPT Actions 等に渡せる OpenAPI

ローカル外へ公開する場合は必ずトークンを設定してください:

```bash
CADENCE_API_TOKEN='長いランダム文字列' python3 run_api.py --host 0.0.0.0
```

---

## テスト

```bash
PYTHONPATH=$(pwd) python3 -m unittest discover -s tests -t .
```

109 テスト全合格を確認しています。

---

## データとプライバシー

- すべてローカルのみ。第三者送信・広告利用は一切なし。
- DB: `cadence.db`（リポジトリ直下・`.gitignore` で除外済み）
- 全消去したいとき: `rm cadence.db`

---

## 約束（ツールに焼き込んだ安全ガード）

- 診断・断定をしない（「あなたは躁です」とは言わない）
- 薬の量・やめ方・飲み合わせには立ち入らない（主治医へ）
- ストリーク強要・罰・恥・他者比較・ランキングをしない
- 通知は最小限。記録を目的化させない
- 危機のサインは取りこぼさず、専門窓口へ繋ぐ

補助であって、治療の代わりではありません。

---

## 公式 Registry への掲載について

`server.json` は MCP 公式 Registry 向けのメタデータです。PyPI 公開後に有効になります。
それまでは `git clone` + `python3 run.py` でご利用ください。

---

## ライセンス

MIT License — Copyright (c) 2026 RYOSEIWORLD

相談窓口の番号・受付時間は、厚生労働省「まもろうよ こころ」と各運営団体の公式情報で確認済みです。
