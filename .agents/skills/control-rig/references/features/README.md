# rig Feature Map

Canonical machine-readable feature map: [`../features.json`](../features.json).
Validated in CI and `pnpm verify` via `node tools/control-rig.mjs map --check`.

| Route / Tool | Feature | Source | Verify |
| :----------- | :------ | :----- | :----- |
| `/` | Status board HTML | `src/app.tsx`, `src/views/status.tsx` | `node tools/control-rig.mjs request GET / --contains "<!doctype html>"` |
| `/health` | JSON health & lane endpoint | `src/app.tsx`, `src/lane.ts` | `node tools/control-rig.mjs health --sha HEAD` |
| `/digest/:night` | Morning digest HTML | `src/app.tsx`, `src/views/digest.tsx` | `node tools/control-rig.mjs request GET /digest/2026-10-28 --contains "2026-10-28"` |
| `/api/digest/:night` | Morning digest JSON API | `src/app.tsx`, `src/digest/reader.ts` | `node tools/control-rig.mjs request GET /api/digest/2026-10-28 --contains "lastStatus"` |
| `/watchdog` | Watchdog control center HTML | `src/app.tsx`, `mcp-server/static/watchdog.html` | `node tools/control-rig.mjs request GET /watchdog --contains "T3 & Antigravity Self-Healing Control Center"` |
| `/watchdog/api/status` | Watchdog status JSON snapshot | `src/app.tsx` | `node tools/control-rig.mjs request GET /watchdog/api/status --contains "safe-write"` |
| `mcp:watchdog` | Python MCP session watchdog tool | `mcp-server/tools/watchdog.py` | `node tools/control-rig.mjs execute` |
