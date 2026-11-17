---
name: control-rig
description:
  Use the control-rig CLI for every check of the running rig Hono SSR app and
  Python MCP/remote-worker tools before claiming work is ready.
---

# control-rig

Use `node tools/control-rig.mjs` for every local check of `rig` before claiming
work is ready.

## Commands

```sh
node tools/control-rig.mjs doctor
node tools/control-rig.mjs dev
node tools/control-rig.mjs login
node tools/control-rig.mjs request GET / --contains "lane-07"
node tools/control-rig.mjs request GET /digest/2026-10-28 --contains "2026-10-28"
node tools/control-rig.mjs execute
node tools/control-rig.mjs map --check
node tools/control-rig.mjs health --sha HEAD
node tools/control-rig.mjs stop
```

Add `--json` to any command for machine-readable output.

## Auth & Fixtures Notes

- **Auth (`login`):** Explicit no-op (`n/a`). Per [`docs/vision.md`](../../../docs/vision.md),
  `rig` is not a place for secrets and has no login flow.
- **Night fixtures (`runs/`):** Read-only real night logs (`runs/2026-10-27.jsonl`,
  `runs/2026-10-28.jsonl`). Never modify them.
- **Feature Map:** [`references/features.json`](references/features.json) tracks
  every Hono route in `src/app.tsx` and every Python tool module in
  `mcp-server/tools/`. Run `map --check` whenever routes or tools change.
- **Offline smoke (`execute`):** Runs deterministic offline checks of
  `mcp-server/tools/watchdog.py` and `scripts/remote_worker.py` in an isolated
  temp directory without touching `$HOME` or dispatching GitHub Actions.

## Proof

Before opening or finishing a PR:

1. Run `pnpm verify` (`tsc --noEmit`, Python `py_compile`, `pnpm test`, `map --check`).
2. Run `node tools/control-rig.mjs doctor` and `node tools/control-rig.mjs execute`.
3. For route/UI changes, start the server with `node tools/control-rig.mjs dev`,
   verify changed routes with `request --contains` and `health`, then run
   `node tools/control-rig.mjs stop` so no lingering server remains.
4. Cite exact commands and results under **Testing** in the PR description.
