# rig

The lane's resident service: keeps a heartbeat, serves the status board, reads the night's run
log. Hono + JSX, rendered on the server, Node 22+ (`node (pnpm) + python · hono, typescript, vitest, mcp-server`).

Read first: [`docs/vision.md`](docs/vision.md), [`docs/styleguide.md`](docs/styleguide.md).
Decisions: [`docs/adr/README.md`](docs/adr/README.md) (`docs/adr/`).

## Tools & Verification

Use `pnpm` for project checks, `node tools/control-rig.mjs` for local runtime checks, and `gh` for
GitHub pull requests (PRs) and issues.

```sh
pnpm verify
```

`pnpm verify` is the primary local and Continuous Integration (CI) quality gate (`tsc --noEmit`,
Python `py_compile`, `pnpm test`, and `node tools/control-rig.mjs map --check`). Run it before
committing or opening any PR.

- `pnpm dev` / `pnpm start`: serves on `PORT` (8787). Needs `.env` (copy `.env.example`).
- `pnpm test`: Vitest + Python `unittest` (`tests/test_*.py`).
- `pnpm typecheck`: `tsc --noEmit`.
- `node tools/control-rig.mjs <doctor|dev|login|request|execute|map|health>`: local control CLI
  (see [`.agents/skills/control-rig/SKILL.md`](.agents/skills/control-rig/SKILL.md)).

## Boundaries

Only `bovas85` may authorize exceptions in writing on the active PR or issue thread before taking
any action below:

- Push directly to `main` (always work on a feature branch and open a PR).
- Merge any pull request (`bovas85` owns all merges; hand back when ready).
- Commit secrets, tokens, API keys, `.env` values, or previews into code, issues, or PRs
  (abort and redact immediately if discovered).
- Modify `runs/`: those are real nights, read-only fixtures.
- Add client-side JavaScript to `rig` pages (ADR 0001: server-rendered JSX only).
- Self-review `medium` or `high` risk PRs with the coding agent (spawn an independent subagent
  using the `review-pr` skill, or ask `bovas85` if subagent execution is unavailable).

## How work moves here

1. A feature starts as a plan: `plan.md` at the root (one at a time). Finished plans live in
   `docs/plans/done/`.
2. The plan is split into GitHub issues: skill `plan-to-issues` (`.agents/skills/`). A human
   reviews the split before anything is published. GitHub issues out of reach: files in
   `docs/issues/` (ADR 0004).
3. Issues are worked by workers, one issue per worker, each on its own branch or worktree.
   Pick the model per issue: the strongest for logic, a cheaper one for views and tests.
4. A worker closes its issue with a closing comment, exactly this shape:

   ```
   done: <what changed, one line>
   worker: <harness> · <model> · <effort>
   commit: <sha or "none">
   ```

5. An issue is closed only when its "Done when" holds. If it can't hold yet, leave it open and
   say what it waits on.

## Skills

Shared skills live in `.agents/skills/`, one folder each, `SKILL.md` inside. That folder is the
one source for every harness on the team. If yours loads skills from somewhere else, point it
here (a link or a config entry). Don't copy: copies drift.

## Map

- Primitives catalog (update `adrs` when changing primitives or ADRs):
  [`docs/primitives.md`](docs/primitives.md)
- Decisions (Architecture Decision Records (ADRs) — read before big changes):
  [`docs/adr/README.md`](docs/adr/README.md)
- Feature flags & rollback runbook:
  [`docs/feature-flags.md`](docs/feature-flags.md),
  [`docs/disaster-recovery.md`](docs/disaster-recovery.md)
- Control CLI & route/tool feature map:
  [`tools/control-rig.mjs`](tools/control-rig.mjs),
  [`.agents/skills/control-rig/SKILL.md`](.agents/skills/control-rig/SKILL.md)
- Shipping & review workflows: `ship-pr`, `review-pr`, and `friction-log` skills
- Issue priority: `P0` > `P1` > `P2` > `P3` (work highest priority first).
- Human decisions: wait on `needs-human` issues until `bovas85` decides.
