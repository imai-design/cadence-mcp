# Cadence AI Integration

Cadence is a local-first tool layer for ADHD and mood-rhythm support. It is
not a diagnostic system and must not be used to make medication or treatment
decisions.

## 1. Claude: MCP over stdio

Use this when Claude Code or Claude Desktop should call Cadence as tools.

```bash
claude mcp add cadence -- python3 /path/to/cadence-mcp/run.py
```

The MCP server exposes 24 tools (12 core + 8 app-specific + 4 care-facility):

- `choose_support_mode`
- `log_daily_checkin`
- `log_social_rhythm`
- `track_rhythm_regularity`
- `build_action_plan`
- `detect_early_warning`
- `break_down_task`
- `list_today_one_thing`
- `create_if_then_plan`
- `start_focus_timer`
- `track_achievement`
- `share_summary_with_supporter`
- `route_to_crisis_support`
- `park_idea`
- `reserve_first_step`
- `start_wind_down`
- `reenter_stalled`
- `low_battery_mode`
- `money_fog`
- `list_due_reminders`
- `support_plan_intake`
- `support_plan_list`
- `support_plan_export_docx`
- `subsidy_precheck`

When the correct tool is unclear, call `choose_support_mode` first with the
user's message. It recommends one tool without diagnosing or auto-executing it.

## 2. Other AI Agents: HTTP API

Start the local API server:

```bash
cadence-api
```

Default URL:

```text
http://127.0.0.1:8787
```

Discovery:

```bash
curl -s http://127.0.0.1:8787/v1/agent-instructions
curl -s http://127.0.0.1:8787/v1/tools
curl -s 'http://127.0.0.1:8787/v1/tools?format=openai'
curl -s 'http://127.0.0.1:8787/v1/tools?format=anthropic'
curl -s http://127.0.0.1:8787/v1/openapi.json
```

Call one tool:

```bash
curl -s http://127.0.0.1:8787/v1/tools/log_daily_checkin/call \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"mood":1,"sleep_hours":7,"note":"落ち着いている"}}'
```

JSON-RPC bridge:

```bash
curl -s http://127.0.0.1:8787/v1/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## 3. OpenAI-style tools

Fetch tool schemas:

```bash
curl -s 'http://127.0.0.1:8787/v1/tools?format=openai'
```

Use the returned `tools` array as function/tool definitions. When a model
chooses a tool, call:

```text
POST /v1/tools/{tool_name}/call
{"arguments": {...}}
```

Then pass `content[0].text` back to the model as the tool result.

## 4. Anthropic-style tools

Fetch tool schemas:

```bash
curl -s 'http://127.0.0.1:8787/v1/tools?format=anthropic'
```

Use the returned `tools` array. When the model requests a tool, call the same
HTTP endpoint:

```text
POST /v1/tools/{tool_name}/call
{"arguments": {...}}
```

## 5. Security

Localhost mode has no token by default. If the API is exposed outside this Mac,
set a token.

```bash
CADENCE_API_TOKEN='long-random-token' \
  cadence-api --host 0.0.0.0 --base-url https://your-tunnel.example
```

Callers must send one of:

```text
X-Cadence-Token: long-random-token
Authorization: Bearer long-random-token
```

The server refuses `--host 0.0.0.0` without a token.

## 6. Agent Safety Contract

Any AI using Cadence must follow these rules:

- Do not diagnose the user or describe Cadence as medical-grade.
- Do not advise medication dose changes, discontinuation, or interactions.
- If crisis language appears, call `route_to_crisis_support` immediately.
- Do not share data with supporters unless the user explicitly consents.
- Do not use streaks, shame, punishment, ranking, or comparison.
- Keep task help tiny: one visible next step is better than a perfect plan.
- Use `low_battery_mode` to reduce choices on low-energy days; never turn it
  into medication instructions.
- Use `money_fog` only to externalize three facts; never provide financial
  advice or borrowing recommendations.
