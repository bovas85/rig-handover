# Primitives Catalog

Core building blocks, code roots, and active ADRs. Any PR that adds or reshapes
a primitive, or writes or supersedes an ADR, must update the matching `adrs`
list in the same PR.

## 1. Heartbeat & Lane Identity

- **Roots:** `src/heartbeat.ts`, `src/lane.ts`, `src/config.ts`, `src/server.ts`,
  `rig.json`, `var/heartbeat.json`
- **Role:** Writes a periodic heartbeat JSON file (`beatEverySeconds` from
  `rig.json`), resolves `LANE_ID` and `LANE_MARKER` from `.env` / environment,
  and boots the Hono Node server on `PORT`.
- **adrs:**
  - [`docs/adr/0003-previews-are-public-and-short-lived.md`](adr/0003-previews-are-public-and-short-lived.md)

## 2. Server-Rendered Status Board & Morning Digest

- **Roots:** `src/app.tsx`, `src/status.ts`, `src/digest/reader.ts`,
  `src/digest/types.ts`, `src/views/layout.tsx`, `src/views/status.tsx`,
  `src/views/digest.tsx`, `runs/*.jsonl`
- **Role:** Renders `/`, `/health`, `/digest/:night`, and `/api/digest/:night`
  from read-only night logs (`runs/<YYYY-MM-DD>.jsonl`) using `hono/jsx` with
  one inline stylesheet and zero client JS on `rig` pages.
- **adrs:**
  - [`docs/adr/0001-server-rendered-jsx-no-client-js.md`](adr/0001-server-rendered-jsx-no-client-js.md)
  - [`docs/adr/0003-previews-are-public-and-short-lived.md`](adr/0003-previews-are-public-and-short-lived.md)

## 3. Watchdog MCP Tool & Remote Worker

- **Roots:** `mcp-server/config.py`, `mcp-server/tools/watchdog.py`,
  `mcp-server/static/watchdog.html`, `scripts/remote_worker.py`,
  `.github/workflows/remote-worker.yml`, `src/app.tsx` (`/watchdog`,
  `/watchdog/api/status`)
- **Role:** Detects stuck sessions and subshell traps, provides MCP tool
  actions (`status`, `scan_and_heal`, `interrupt_thread`, `query_axiom`), and
  executes isolated remote worker payloads (`python`, `shell`, `http`,
  `mcp_sequence`).
- **adrs:**
  - [`docs/adr/0001-server-rendered-jsx-no-client-js.md`](adr/0001-server-rendered-jsx-no-client-js.md)

## 4. Local Control CLI & Feature Map

- **Roots:** `tools/control-rig.mjs`, `tools/control-rig.d.mts`,
  `.agents/skills/control-rig/SKILL.md`,
  `.agents/skills/control-rig/references/features.json`
- **Role:** Unified local verification CLI (`doctor`, `dev`, `stop`, `login`,
  `request`, `execute`, `map`, `health`) keeping all Hono routes and Python
  tools synced with `features.json`.
- **adrs:**
  - [`docs/adr/0001-server-rendered-jsx-no-client-js.md`](adr/0001-server-rendered-jsx-no-client-js.md)
  - [`docs/adr/0003-previews-are-public-and-short-lived.md`](adr/0003-previews-are-public-and-short-lived.md)

## 5. Plans, Issues & Autonomous Maintenance Loop

- **Roots:** `AGENTS.md`, `.agents/skills/plan-to-issues/SKILL.md`,
  `docs/plans/done/`, `docs/issues/`, `.github/ship-pr.json`,
  `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/`,
  `.github/scripts/issue-triage.cjs`, `.github/workflows/`
- **Role:** Splits `plan.md` into GitHub issues (or `docs/issues/` fallback),
  triages `P0`–`P3` and `needs-human`, files zero-cost CI failure issues via
  `errors-to-issues.yml` (with local T3/Antigravity scheduled maintenance),
  and enforces branch + human merge rules.
- **adrs:**
  - [`docs/adr/0002-plans-are-files-work-is-issues.md`](adr/0002-plans-are-files-work-is-issues.md)
  - [`docs/adr/0004-issues-on-github-or-as-files.md`](adr/0004-issues-on-github-or-as-files.md)
