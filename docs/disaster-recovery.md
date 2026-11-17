# Disaster Recovery Runbook: rig

This runbook defines procedures for diagnosing incidents, rolling back faulty
changes, and restoring `rig` (`node (pnpm) + python · hono, typescript, vitest,
mcp-server`).

## 1. System Architecture

- **Resident Service:** Node 22+ Hono JSX server (`src/server.ts`, default
  `http://127.0.0.1:8787`).
- **Ephemeral Heartbeat:** `var/heartbeat.json` overwritten every
  `beatEverySeconds` (60s in `rig.json`).
- **Run Logs:** Read-only night fixtures in `runs/<YYYY-MM-DD>.jsonl`.
- **Automation & Tools:** `mcp-server/tools/watchdog.py` and
  `scripts/remote_worker.py`.
- **Health Endpoint:** `GET /health` returning `{ ok: true, lane }`.

## 2. Incident Detection & Monitoring

Verify local health and runtime integrity with `control-rig`:

```sh
node tools/control-rig.mjs doctor
node tools/control-rig.mjs health --sha HEAD
node tools/control-rig.mjs execute
```

Or query the live endpoint directly:

```sh
curl -fsSL http://127.0.0.1:8787/health
```

## 3. Rollback Procedures

### Method A: Git Revert via Branch & PR (Standard)

1. Sync `main` and create a revert branch:

   ```sh
   git checkout main
   git pull origin main
   git checkout -b fix/revert-<short-sha>
   git revert <BROKEN_COMMIT_SHA> -m 1
   ```

2. Validate locally before pushing:

   ```sh
   pnpm verify
   ```

3. Push the branch, open a PR targeting `main`, and hand off to `bovas85` for
   merge. Never push directly to `main`.

### Method B: Local Emergency Restart on Last Known-Good Commit

If a local lane instance is broken during an incident:

1. Stop the running server (`node tools/control-rig.mjs stop` or supervisor
   service restart).
2. Check out the last known-good commit in a clean worktree, run
   `pnpm install --frozen-lockfile`, and start with `pnpm start`.
3. Confirm `/health` responds `200 OK` with `{ "ok": true, "lane": "..." }`.

## 4. Post-Incident Verification Checklist

- [ ] Run `pnpm verify` (`tsc --noEmit`, `py_compile`, `pnpm test`,
      `node tools/control-rig.mjs map --check`).
- [ ] Run `node tools/control-rig.mjs doctor` and
      `node tools/control-rig.mjs execute`.
- [ ] Verify `/`, `/health`, and `/digest/2026-10-28` via `control-rig request`.
- [ ] File a `friction` issue or regression test before re-proposing the
      reverted change.

## 5. Backups & Restore (Rung 9: `n/a` Database Justification)

Database backups and restore drills are explicitly **`n/a`** for `rig`:

- Per [`docs/vision.md`](vision.md), `rig` has no database ("If a feature needs
  a database, it belongs somewhere else").
- Night run logs (`runs/*.jsonl`) are immutable, read-only fixtures tracked
  directly in git history (`git checkout -- runs/` restores them immediately).
- `var/heartbeat.json` is ephemeral runtime state recreated automatically on
  server startup by `startBeating()` in [`src/heartbeat.ts`](../src/heartbeat.ts).
