# Feature Flags & Configuration Toggles

Runtime flags and lane configuration toggles in `rig` default to safe
operational values and can be overridden via `.env` / environment variables or
[`rig.json`](../rig.json).

## Metrics Policy

No automated flag-metrics or telemetry SDK is active (`metrics: none`). Changes
are evaluated via `pnpm verify`, `node tools/control-rig.mjs` checks, and local
or CI verification.

## Active Flags & Toggles

| Flag / Setting | Source / Env Override | Owner | Metric | Removal / Lifecycle Rule |
| :------------- | :-------------------- | :---- | :----- | :----------------------- |
| `ENABLE_ADD_VALIDATION_TESTS_AND` | `src/app.tsx`, `mcp-server/tools/watchdog.py` (`ENABLE_ADD_VALIDATION_TESTS_AND`) | `bovas85` | `none` | Temporary rollout gate for `/watchdog`, `/watchdog/api/status`, and watchdog validation tests; remove after 14 days stable on `main` with `pnpm verify` green. |
| `LANE_MARKER` | `src/lane.ts` (`LANE_MARKER` in `.env`) | `bovas85` | `none` | Permanent per-lane banner toggle; MUST be unset before saving final public preview HTML (ADR 0003). |
| `LANE_ID` | `src/lane.ts` (`LANE_ID` in `.env`, default `lane-07`) | `bovas85` | `none` | Permanent lane identifier exposed on `/health` and rendered layout. |
| `rig.json` (`adapter`, `beatEverySeconds`, `runsDir`) | `src/config.ts` ([`rig.json`](../rig.json)) | `bovas85` | `none` | Permanent service config controlling heartbeat cadence and read-only `runs/` directory. |
| Watchdog config (`auto_heal_subshells`, `auto_interrupt_threads`, `auto_heal_enabled`) | `mcp-server/tools/watchdog.py` (`~/.local/share/t3-watchdog/config.json`) | `bovas85` | `none` | Permanent operational guardrails (`auto_interrupt_threads` defaults `false` for safety). |

## Cleanup Protocol

When a temporary rollout flag (such as `ENABLE_ADD_VALIDATION_TESTS_AND`) meets
its removal condition, file a `chore(cleanup):` issue using
[`.github/ISSUE_TEMPLATE/cleanup.yml`](../.github/ISSUE_TEMPLATE/cleanup.yml)
with **Ready when** and **How to verify** sections so local T3/Antigravity
scheduled maintenance can remove the flag and fallback branch cleanly.
