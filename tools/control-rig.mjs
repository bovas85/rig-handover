#!/usr/bin/env node

/**
 * control-rig.mjs
 *
 * Unified local control CLI for rig (Hono SSR + Python MCP/remote worker).
 * Commands: doctor, dev, stop, login, request, execute, map, health
 */

import { execFileSync, spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
export const ROOT_DIR = path.resolve(__dirname, '..');
export const FEATURES_PATH = path.join(
  ROOT_DIR,
  '.agents/skills/control-rig/references/features.json',
);
const AUTOPILOT_DIR = path.join(ROOT_DIR, '.autopilot');
const DEV_ORIGIN_PATH = path.join(AUTOPILOT_DIR, 'dev.origin');
const DEV_PID_PATH = path.join(AUTOPILOT_DIR, 'dev.pid');
const DEFAULT_LOCAL_ORIGIN = `http://127.0.0.1:${process.env.PORT || 8787}`;

const BOOLEAN_FLAGS = new Set(['json', 'check', 'help']);

export function parseCliArgs(argv) {
  const positionals = [];
  const flags = {};

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg.startsWith('--')) {
      const eqIdx = arg.indexOf('=');
      if (eqIdx !== -1) {
        flags[arg.slice(2, eqIdx)] = arg.slice(eqIdx + 1);
      } else {
        const key = arg.slice(2);
        const next = argv[i + 1];
        if (!BOOLEAN_FLAGS.has(key) && next !== undefined && !next.startsWith('--')) {
          flags[key] = next;
          i += 1;
        } else {
          flags[key] = true;
        }
      }
    } else {
      positionals.push(arg);
    }
  }

  return {
    command: positionals[0] || 'help',
    positionals: positionals.slice(1),
    flags,
  };
}

function outputResult(payload, asJson, humanLines) {
  if (asJson) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    for (const line of humanLines) {
      console.log(line);
    }
  }
}

export function normalizeOrigin(origin) {
  return String(origin || DEFAULT_LOCAL_ORIGIN).replace(/\/$/, '');
}

export function resolveLocalOrigin(explicitOrigin, rootDir = ROOT_DIR) {
  if (explicitOrigin) return normalizeOrigin(explicitOrigin);
  const originFile = path.join(rootDir, '.autopilot/dev.origin');
  if (fs.existsSync(originFile)) {
    const saved = fs.readFileSync(originFile, 'utf8').trim();
    if (saved) return normalizeOrigin(saved);
  }
  return DEFAULT_LOCAL_ORIGIN;
}

export function discoverRoutes(rootDir = ROOT_DIR) {
  const routes = new Set();

  const appFile = path.join(rootDir, 'src/app.tsx');
  if (fs.existsSync(appFile)) {
    const src = fs.readFileSync(appFile, 'utf8');
    const routeRe = /\bapp\.(?:get|post|put|patch|delete)\(\s*['"`]([^'"`]+)['"`]/g;
    let match;
    while ((match = routeRe.exec(src)) !== null) {
      routes.add(match[1]);
    }
  }

  const toolsDir = path.join(rootDir, 'mcp-server/tools');
  if (fs.existsSync(toolsDir)) {
    for (const entry of fs.readdirSync(toolsDir, { withFileTypes: true })) {
      if (
        entry.isFile() &&
        entry.name.endsWith('.py') &&
        entry.name !== '__init__.py'
      ) {
        const stem = entry.name.slice(0, -3);
        routes.add(`mcp:${stem}`);
      }
    }
  }

  return Array.from(routes).sort();
}

export function validateFeatureMap(
  rootDir = ROOT_DIR,
  featuresPath = path.join(rootDir, '.agents/skills/control-rig/references/features.json'),
) {
  const codeRoutes = discoverRoutes(rootDir);
  if (!fs.existsSync(featuresPath)) {
    return {
      ok: false,
      errors: [`Feature map file missing: ${path.relative(rootDir, featuresPath)}`],
      codeRoutes,
      mappedRoutes: [],
      entries: [],
    };
  }

  const raw = JSON.parse(fs.readFileSync(featuresPath, 'utf8'));
  const entries = Array.isArray(raw.features) ? raw.features : [];
  const mappedRoutes = entries.map((e) => e.route).sort();
  const errors = [];

  for (const route of codeRoutes) {
    if (!mappedRoutes.includes(route)) {
      errors.push(`Route/tool in code missing from Feature Map: ${route}`);
    }
  }
  for (const entry of entries) {
    if (!codeRoutes.includes(entry.route)) {
      errors.push(`Feature Map references non-existent route/tool: ${entry.route}`);
    }
    if (!entry.feature || typeof entry.feature !== 'string') {
      errors.push(`Feature Map entry "${entry.route}" missing "feature" title`);
    }
    if (!entry.source || typeof entry.source !== 'string') {
      errors.push(`Feature Map entry "${entry.route}" missing "source" path`);
    }
    if (!entry.reach || typeof entry.reach !== 'string') {
      errors.push(`Feature Map entry "${entry.route}" missing "reach" notes`);
    }
    if (!Array.isArray(entry.actions) || entry.actions.length === 0) {
      errors.push(`Feature Map entry "${entry.route}" missing "actions" list`);
    }
    if (!entry.verify || typeof entry.verify !== 'string') {
      errors.push(`Feature Map entry "${entry.route}" missing "verify" instructions`);
    }
  }

  return { ok: errors.length === 0, errors, codeRoutes, mappedRoutes, entries };
}

export function runDoctor(rootDir = ROOT_DIR, flags = {}) {
  const checks = [];

  const majorNode = Number(process.versions.node.split('.')[0]);
  checks.push({
    name: 'node',
    ok: majorNode >= 22,
    detail: `v${process.versions.node}`,
    fix: 'Install Node >= 22',
  });

  const pnpmRes = spawnSync('pnpm', ['--version'], { encoding: 'utf8' });
  checks.push({
    name: 'pnpm',
    ok: pnpmRes.status === 0,
    detail: pnpmRes.status === 0 ? `v${pnpmRes.stdout.trim()}` : 'missing',
    fix: 'Install pnpm (corepack enable && corepack prepare pnpm@10 --activate)',
  });

  const pyRes = spawnSync('python3', ['--version'], { encoding: 'utf8' });
  checks.push({
    name: 'python3',
    ok: pyRes.status === 0,
    detail: pyRes.status === 0 ? pyRes.stdout.trim() : 'missing',
    fix: 'Install Python 3.12+',
  });

  const hasNodeModules = fs.existsSync(path.join(rootDir, 'node_modules'));
  checks.push({
    name: 'node_modules',
    ok: hasNodeModules,
    detail: hasNodeModules ? 'installed' : 'missing',
    fix: 'Run: pnpm install --frozen-lockfile',
  });

  const rigJsonPath = path.join(rootDir, 'rig.json');
  let rigConfig = null;
  let rigOk = false;
  let rigDetail = 'missing';
  if (fs.existsSync(rigJsonPath)) {
    try {
      rigConfig = JSON.parse(fs.readFileSync(rigJsonPath, 'utf8'));
      rigOk =
        typeof rigConfig.beatEverySeconds === 'number' &&
        typeof rigConfig.runsDir === 'string';
      rigDetail = rigOk
        ? `adapter=${rigConfig.adapter}, runsDir=${rigConfig.runsDir}`
        : 'missing required fields (beatEverySeconds, runsDir)';
    } catch (err) {
      rigDetail = err instanceof Error ? err.message : String(err);
    }
  }
  checks.push({
    name: 'rig_json',
    ok: rigOk,
    detail: rigDetail,
    fix: 'Ensure valid rig.json in repository root',
  });

  const runsDirName = rigConfig?.runsDir || 'runs';
  const runsDirPath = path.join(rootDir, runsDirName);
  let runsOk = false;
  let runsDetail = 'missing';
  if (fs.existsSync(runsDirPath) && fs.statSync(runsDirPath).isDirectory()) {
    const jsonlFiles = fs
      .readdirSync(runsDirPath)
      .filter((f) => /^\d{4}-\d{2}-\d{2}\.jsonl$/.test(f));
    runsOk = jsonlFiles.length > 0;
    runsDetail = `${jsonlFiles.length} night fixture(s) in ${runsDirName}/`;
  }
  checks.push({
    name: 'runs_dir',
    ok: runsOk,
    detail: runsDetail,
    fix: `Restore read-only fixtures in ${runsDirName}/`,
  });

  const varDirPath = path.join(rootDir, 'var');
  let varOk = false;
  let varDetail = 'unwritable';
  if (fs.existsSync(varDirPath)) {
    varOk = fs.statSync(varDirPath).isDirectory();
    varDetail = varOk ? 'var/ directory present' : 'var exists but is not a directory';
  } else {
    try {
      fs.accessSync(rootDir, fs.constants.W_OK);
      varOk = true;
      varDetail = 'var/ not created yet (repo root writable for heartbeat)';
    } catch {
      varOk = false;
      varDetail = 'var/ missing and repo root not writable';
    }
  }
  checks.push({
    name: 'var_dir',
    ok: varOk,
    detail: varDetail,
    fix: 'Ensure var/ is a writable directory (created automatically by heartbeat)',
  });

  const controlSkillOk = fs.existsSync(
    path.join(rootDir, '.agents/skills/control-rig/SKILL.md'),
  );
  const planSkillOk = fs.existsSync(
    path.join(rootDir, '.agents/skills/plan-to-issues/SKILL.md'),
  );
  const mirrorIssues = [];
  for (const rel of ['.claude/skills', '.gemini/skills']) {
    const p = path.join(rootDir, rel);
    if (fs.existsSync(p)) {
      const stat = fs.lstatSync(p);
      if (!stat.isSymbolicLink()) {
        mirrorIssues.push(`${rel} is not a symlink to .agents/skills`);
      }
    }
  }
  const skillsOk = controlSkillOk && planSkillOk && mirrorIssues.length === 0;
  checks.push({
    name: 'skills_policy',
    ok: skillsOk,
    detail: skillsOk
      ? '.agents/skills/ canonical (control-rig, plan-to-issues)'
      : `control-rig=${controlSkillOk}, plan-to-issues=${planSkillOk}${mirrorIssues.length ? `; ${mirrorIssues.join(', ')}` : ''}`,
    fix: 'Keep canonical skills in .agents/skills/ and link (never copy) harness directories',
  });

  const mapValidation = validateFeatureMap(rootDir);
  checks.push({
    name: 'feature_map',
    ok: mapValidation.ok,
    detail: mapValidation.ok
      ? `${mapValidation.codeRoutes.length} routes/tools synced`
      : mapValidation.errors.join('; '),
    fix: 'Update .agents/skills/control-rig/references/features.json',
  });

  return { ok: checks.every((c) => c.ok), checks, flags };
}

async function cmdDoctor(flags) {
  const result = runDoctor(ROOT_DIR, flags);
  if (flags.origin) {
    const origin = normalizeOrigin(flags.origin);
    try {
      const res = await fetch(`${origin}/health`, {
        signal: AbortSignal.timeout(4000),
      });
      result.checks.push({
        name: 'health_endpoint',
        ok: res.ok,
        detail: `${origin}/health -> HTTP ${res.status}`,
        fix: 'Start local dev server with: node tools/control-rig.mjs dev',
      });
    } catch (err) {
      result.checks.push({
        name: 'health_endpoint',
        ok: false,
        detail: err instanceof Error ? err.message : String(err),
        fix: 'Start local dev server with: node tools/control-rig.mjs dev',
      });
    }
    result.ok = result.checks.every((c) => c.ok);
  }

  const lines = result.checks.map(
    (c) =>
      `${c.ok ? '[ok]' : '[fail]'} ${c.name}: ${c.detail}${c.ok ? '' : ` | Fix: ${c.fix}`}`,
  );
  outputResult({ ok: result.ok, checks: result.checks }, Boolean(flags.json), lines);
  if (!result.ok) process.exitCode = 1;
}

function getFreePort(preferredPort) {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once('error', () => {
      const fallback = net.createServer();
      fallback.listen(0, '127.0.0.1', () => {
        const addr = fallback.address();
        const chosen = typeof addr === 'object' && addr ? addr.port : 8787;
        fallback.close((err) => (err ? reject(err) : resolve(chosen)));
      });
    });
    srv.listen(preferredPort, '127.0.0.1', () => {
      srv.close((err) => (err ? reject(err) : resolve(preferredPort)));
    });
  });
}

async function isServerHealthy(origin) {
  try {
    const res = await fetch(`${origin}/health`, {
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return false;
    const data = await res.json().catch(() => null);
    return Boolean(data && data.ok === true);
  } catch {
    return false;
  }
}

async function cmdDev(flags) {
  const preferred = Number(flags.port || process.env.PORT || 8787);
  const existingOrigin = flags.port
    ? `http://127.0.0.1:${preferred}`
    : resolveLocalOrigin();

  if (await isServerHealthy(existingOrigin)) {
    outputResult(
      { ok: true, reused: true, origin: existingOrigin },
      Boolean(flags.json),
      [`Reusing healthy server at ${existingOrigin}`],
    );
    return;
  }

  const port = flags.port ? preferred : await getFreePort(preferred);
  const origin = `http://127.0.0.1:${port}`;

  fs.mkdirSync(AUTOPILOT_DIR, { recursive: true });
  const logPath = path.join(AUTOPILOT_DIR, 'dev.log');
  const outFd = fs.openSync(logPath, 'a');

  const tsxBin = path.join(ROOT_DIR, 'node_modules/.bin/tsx');
  const cmd = fs.existsSync(tsxBin) ? tsxBin : 'pnpm';
  const args = fs.existsSync(tsxBin)
    ? ['--env-file-if-exists=.env', 'src/server.ts']
    : ['exec', 'tsx', '--env-file-if-exists=.env', 'src/server.ts'];

  const child = spawn(cmd, args, {
    cwd: ROOT_DIR,
    detached: true,
    stdio: ['ignore', outFd, outFd],
    env: { ...process.env, PORT: String(port) },
  });
  child.unref();
  fs.closeSync(outFd);
  fs.writeFileSync(DEV_PID_PATH, String(child.pid));

  const deadline = Date.now() + Number(flags.timeout || 20) * 1000;
  while (Date.now() < deadline) {
    if (await isServerHealthy(origin)) {
      fs.writeFileSync(DEV_ORIGIN_PATH, origin);
      outputResult(
        { ok: true, reused: false, pid: child.pid, origin, logPath },
        Boolean(flags.json),
        [`Started local server at ${origin} (pid ${child.pid})`],
      );
      return;
    }
    await new Promise((r) => setTimeout(r, 400));
  }

  try {
    process.kill(child.pid, 'SIGTERM');
  } catch {
    // Ignore if already exited
  }
  outputResult(
    {
      ok: false,
      error: `Timed out waiting for ${origin}/health`,
      logPath,
    },
    Boolean(flags.json),
    [`Failed to start server at ${origin}. Check ${logPath}`],
  );
  process.exitCode = 1;
}

function cmdStop(flags) {
  if (!fs.existsSync(DEV_PID_PATH)) {
    outputResult(
      { ok: true, stopped: false, reason: 'No dev.pid file found' },
      Boolean(flags.json),
      ['No running control-rig dev server tracked.'],
    );
    return;
  }
  const pid = Number(fs.readFileSync(DEV_PID_PATH, 'utf8').trim());
  let stopped = false;
  if (Number.isInteger(pid) && pid > 0) {
    try {
      process.kill(pid, 'SIGTERM');
      stopped = true;
    } catch {
      stopped = false;
    }
  }
  fs.rmSync(DEV_PID_PATH, { force: true });
  fs.rmSync(DEV_ORIGIN_PATH, { force: true });
  outputResult(
    { ok: true, stopped, pid },
    Boolean(flags.json),
    [stopped ? `Stopped dev server (pid ${pid})` : `Cleaned stale pid file (${pid})`],
  );
}

function cmdLogin(flags) {
  const payload = {
    ok: true,
    status: 'n/a',
    reason: 'No authentication required (per docs/vision.md: rig is not a place for secrets)',
  };
  outputResult(payload, Boolean(flags.json), [
    'login: n/a (no authentication required per docs/vision.md)',
  ]);
}

export async function performRequest({
  method = 'GET',
  targetPath = '/',
  origin = DEFAULT_LOCAL_ORIGIN,
  contains,
  data,
  dump,
  expectedStatus,
}) {
  const base = normalizeOrigin(origin);
  const url = targetPath.startsWith('http')
    ? targetPath
    : `${base}${targetPath.startsWith('/') ? targetPath : `/${targetPath}`}`;

  const headers = { Accept: 'text/html,application/json,*/*' };
  let body;
  if (data !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = typeof data === 'string' ? data : JSON.stringify(data);
  }

  const res = await fetch(url, {
    method: method.toUpperCase(),
    headers,
    body,
    signal: AbortSignal.timeout(15000),
  });
  const text = await res.text();

  if (dump) {
    fs.mkdirSync(path.dirname(path.resolve(dump)), { recursive: true });
    fs.writeFileSync(path.resolve(dump), text, 'utf8');
  }

  const statusOk =
    expectedStatus !== undefined ? res.status === Number(expectedStatus) : res.ok;
  const containsOk = contains ? text.includes(String(contains)) : true;
  const ok = statusOk && containsOk;
  return {
    ok,
    url,
    status: res.status,
    contains: contains || null,
    containsMatched: containsOk,
    bytes: Buffer.byteLength(text),
    snippet: text.slice(0, 240),
  };
}

async function cmdRequest(positionals, flags) {
  const method = positionals[0] || 'GET';
  const targetPath = positionals[1] || '/';
  const origin = resolveLocalOrigin(flags.origin);
  const result = await performRequest({
    method,
    targetPath,
    origin,
    contains: typeof flags.contains === 'string' ? flags.contains : undefined,
    data: typeof flags.data === 'string' ? flags.data : undefined,
    dump: typeof flags.dump === 'string' ? flags.dump : undefined,
    expectedStatus: flags.status !== undefined ? Number(flags.status) : undefined,
  });

  outputResult(result, Boolean(flags.json), [
    `${method.toUpperCase()} ${result.url} -> ${result.status} (${result.bytes} bytes)`,
    result.contains
      ? `contains "${result.contains}": ${result.containsMatched ? 'matched' : 'MISSING'}`
      : 'contains check: skipped',
  ]);
  if (!result.ok) process.exitCode = 1;
}

export function runOfflineSmoke(rootDir = ROOT_DIR) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'control-rig-smoke-'));
  try {
    const watchdogSmokeScript = [
      'import json, os, sys, tempfile',
      'from pathlib import Path',
      'repo = Path(sys.argv[1])',
      'tmp = Path(sys.argv[2])',
      'sys.path.insert(0, str(repo / "mcp-server"))',
      'sys.path.insert(0, str(repo / "mcp-server" / "tools"))',
      'import watchdog',
      'watchdog.T3_STATE_DB = tmp / "missing_statev2.sqlite"',
      'watchdog.T3_BRAINS_DIR = tmp / "brains"',
      'watchdog.WATCHDOG_STATE_DIR = tmp / "state"',
      'watchdog.WATCHDOG_LOG_FILE = watchdog.WATCHDOG_STATE_DIR / "events.jsonl"',
      'watchdog.WATCHDOG_CONFIG_FILE = watchdog.WATCHDOG_STATE_DIR / "config.json"',
      'watchdog.WATCHDOG_T3_TOKEN_FILE = watchdog.WATCHDOG_STATE_DIR / "t3-mcp-token.txt"',
      'watchdog.SESSION_HYGIENE_SKILL = tmp / "SKILL.md"',
      'status_res = watchdog.run_watchdog_mcp_tool({"action": "status"})',
      'payload = json.loads(status_res["content"][0]["text"])',
      'rc = watchdog.classify_root_cause("hung_subshell_process", "python3 -c " + chr(34) + "`echo hi`" + chr(34))',
      'assert "snapshot" in payload and "summary" in payload["snapshot"]',
      'assert rc.get("root_cause_code") == "backtick_subshell_in_double_quotes", rc',
      'print(json.dumps({"ok": True, "summary": payload["snapshot"]["summary"], "root_cause_code": rc["root_cause_code"]}))',
    ].join('\n');

    const wdProc = spawnSync('python3', ['-', rootDir, tmpDir], {
      input: watchdogSmokeScript,
      encoding: 'utf8',
    });
    if (wdProc.status !== 0) {
      return {
        ok: false,
        watchdog: { ok: false, stderr: wdProc.stderr, stdout: wdProc.stdout },
        remoteWorker: null,
      };
    }

    const rwPayload = {
      mode: 'python',
      code: "print('remote_worker_smoke_ok')",
    };
    const b64 = Buffer.from(JSON.stringify(rwPayload), 'utf8').toString('base64');
    const rwScript = path.join(rootDir, 'scripts/remote_worker.py');
    const rwWorkDir = path.join(tmpDir, 'rw');
    fs.mkdirSync(rwWorkDir, { recursive: true });

    const rwProc = spawnSync('python3', [rwScript, '--payload-b64', b64], {
      cwd: rwWorkDir,
      encoding: 'utf8',
    });
    const outFile = path.join(rwWorkDir, 'worker_output.json');
    const rwOut = fs.existsSync(outFile)
      ? JSON.parse(fs.readFileSync(outFile, 'utf8'))
      : null;

    const rwOk =
      rwProc.status === 0 &&
      rwOut?.status === 'ok' &&
      String(rwOut?.output?.stdout || '').includes('remote_worker_smoke_ok');

    return {
      ok: Boolean(rwOk),
      watchdog: { ok: true, result: JSON.parse(wdProc.stdout.trim()) },
      remoteWorker: {
        ok: rwOk,
        status: rwOut?.status ?? 'missing',
        stdout: rwOut?.output?.stdout ?? rwProc.stdout,
      },
    };
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

async function cmdExecute(flags) {
  const codeFile = flags['code-file'];
  if (!codeFile || typeof codeFile !== 'string') {
    const smoke = runOfflineSmoke(ROOT_DIR);
    outputResult(smoke, Boolean(flags.json), [
      `[${smoke.watchdog?.ok ? 'ok' : 'fail'}] watchdog.py offline smoke`,
      `[${smoke.remoteWorker?.ok ? 'ok' : 'fail'}] remote_worker.py offline smoke`,
    ]);
    if (!smoke.ok) process.exitCode = 1;
    return;
  }

  const absFile = path.resolve(codeFile);
  const origin = resolveLocalOrigin(flags.origin);

  if (absFile.endsWith('.json')) {
    const spec = JSON.parse(fs.readFileSync(absFile, 'utf8'));
    if (Array.isArray(spec.requests)) {
      const results = [];
      for (const step of spec.requests) {
        const r = await performRequest({
          method: step.method || 'GET',
          targetPath: step.path || '/',
          origin,
          contains: step.contains,
          data: step.body,
          expectedStatus: step.expectedStatus,
        });
        results.push(r);
      }
      const ok = results.every((r) => r.ok);
      outputResult(
        { ok, origin, results },
        Boolean(flags.json),
        results.map((r) => `${r.ok ? '[ok]' : '[fail]'} ${r.url} -> ${r.status}`),
      );
      if (!ok) process.exitCode = 1;
      return;
    }

    if (spec.mode === 'python' || spec.mode === 'shell') {
      const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'control-rig-exec-'));
      try {
        const b64 = Buffer.from(JSON.stringify(spec), 'utf8').toString('base64');
        const rwProc = spawnSync(
          'python3',
          [path.join(ROOT_DIR, 'scripts/remote_worker.py'), '--payload-b64', b64],
          { cwd: tmpDir, encoding: 'utf8' },
        );
        const outFile = path.join(tmpDir, 'worker_output.json');
        const rwOut = fs.existsSync(outFile)
          ? JSON.parse(fs.readFileSync(outFile, 'utf8'))
          : null;
        const ok = rwProc.status === 0 && rwOut?.status === 'ok';
        outputResult({ ok, output: rwOut }, Boolean(flags.json), [
          `[${ok ? 'ok' : 'fail'}] Executed offline remote_worker fixture ${path.relative(ROOT_DIR, absFile)}`,
        ]);
        if (!ok) process.exitCode = 1;
      } finally {
        fs.rmSync(tmpDir, { recursive: true, force: true });
      }
      return;
    }

    throw new Error(`Unsupported JSON fixture format in ${codeFile}`);
  }

  const mod = await import(absFile);
  if (typeof mod.default !== 'function' && typeof mod.run !== 'function') {
    throw new Error(`Fixture ${codeFile} must export default or run()`);
  }
  const fn = mod.run || mod.default;
  const output = await fn({
    origin,
    request: (opts) => performRequest({ origin, ...opts }),
  });
  outputResult({ ok: true, origin, output }, Boolean(flags.json), [
    `Executed ${path.relative(ROOT_DIR, absFile)} against ${origin}`,
  ]);
}

function cmdMap(positionals, flags) {
  const validation = validateFeatureMap(ROOT_DIR);
  if (flags.check) {
    outputResult(
      validation,
      Boolean(flags.json),
      validation.ok
        ? [`Feature Map valid: ${validation.codeRoutes.length} routes/tools verified.`]
        : validation.errors.map((e) => `[fail] ${e}`),
    );
    if (!validation.ok) process.exitCode = 1;
    return;
  }

  const filter = positionals[0];
  const entries = validation.entries || [];
  const matched = filter
    ? entries.filter(
        (e) =>
          e.route.toLowerCase().includes(filter.toLowerCase()) ||
          e.feature.toLowerCase().includes(filter.toLowerCase()),
      )
    : entries;

  outputResult(
    { ok: validation.ok, features: matched },
    Boolean(flags.json),
    matched.map(
      (e) => `${e.route} (${e.feature}) — reach: ${e.reach} | verify: ${e.verify}`,
    ),
  );
}

export function verifyHealthPayload(data, expectedSha, rootDir = ROOT_DIR) {
  if (!data || data.ok !== true || typeof data.lane !== 'string' || !data.lane) {
    return { ok: false, reason: `Unhealthy payload: ${JSON.stringify(data)}` };
  }
  if (!expectedSha || expectedSha === 'any') {
    return { ok: true, reason: `Healthy (lane=${data.lane})` };
  }

  let targetSha = expectedSha;
  if (expectedSha === 'HEAD') {
    targetSha = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: rootDir,
      encoding: 'utf8',
    }).trim();
  }

  if (!data.commitSha) {
    return {
      ok: true,
      commitSha: null,
      targetSha,
      reason: `Healthy (lane=${data.lane}; /health does not expose commitSha)`,
    };
  }

  const liveSha = String(data.commitSha);
  if (liveSha === targetSha || liveSha.startsWith(targetSha)) {
    return { ok: true, commitSha: liveSha, reason: `Exact commit match (${liveSha})` };
  }
  const ancestor = spawnSync(
    'git',
    ['merge-base', '--is-ancestor', targetSha, liveSha],
    { cwd: rootDir, stdio: 'ignore' },
  );
  if (ancestor.status === 0) {
    return {
      ok: true,
      commitSha: liveSha,
      reason: `Live SHA ${liveSha} includes ${targetSha}`,
    };
  }
  return {
    ok: false,
    commitSha: liveSha,
    reason: `Commit mismatch: live ${liveSha} != expected ${targetSha}`,
  };
}

async function cmdHealth(flags) {
  const origin = resolveLocalOrigin(flags.origin);
  const expectedSha = typeof flags.sha === 'string' ? flags.sha : undefined;
  const res = await fetch(`${origin}/health`, {
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    outputResult(
      { ok: false, origin, status: res.status },
      Boolean(flags.json),
      [`Health check failed: ${origin}/health -> HTTP ${res.status}`],
    );
    process.exitCode = 1;
    return;
  }
  const data = await res.json();
  const verdict = verifyHealthPayload(data, expectedSha);
  outputResult(
    { ok: verdict.ok, origin, data, reason: verdict.reason },
    Boolean(flags.json),
    [`${verdict.ok ? '[ok]' : '[fail]'} ${origin}/health — ${verdict.reason}`],
  );
  if (!verdict.ok) process.exitCode = 1;
}

function printHelp() {
  console.log(`control-rig — Unified control CLI for rig

Usage:
  node tools/control-rig.mjs <command> [options]

Commands:
  doctor [--origin <url>] [--json]               Check runtime, rig.json, runs/, var/, skills, feature map
  dev [--port <port>] [--timeout <sec>]          Start detached rig server if not already healthy
  stop                                           Stop detached dev server started by control-rig dev
  login                                          Explicit no-op (n/a per docs/vision.md)
  request <METHOD> <path> [--contains <str>]     Send HTTP request to local rig server
  execute [--code-file <fixture>]                Offline smoke validation of watchdog.py & remote_worker.py
  map [query] [--check] [--json]                 Verify or search route & MCP tool Feature Map
  health [--origin <url>] [--sha <sha>] [--json] Verify /health payload`);
}

async function main() {
  const { command, positionals, flags } = parseCliArgs(process.argv.slice(2));
  if (flags.help || command === 'help') {
    printHelp();
    return;
  }

  switch (command) {
    case 'doctor':
      await cmdDoctor(flags);
      break;
    case 'dev':
      await cmdDev(flags);
      break;
    case 'stop':
      cmdStop(flags);
      break;
    case 'login':
      cmdLogin(flags);
      break;
    case 'request':
      await cmdRequest(positionals, flags);
      break;
    case 'execute':
      await cmdExecute(flags);
      break;
    case 'map':
      cmdMap(positionals, flags);
      break;
    case 'health':
      await cmdHealth(flags);
      break;
    default:
      console.error(`Unknown command: ${command}`);
      printHelp();
      process.exitCode = 1;
  }
}

const isEntrypoint =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename);

if (isEntrypoint) {
  main().catch((err) => {
    console.error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  });
}
