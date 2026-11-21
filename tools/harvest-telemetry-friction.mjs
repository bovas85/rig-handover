#!/usr/bin/env node
/**
 * harvest-telemetry-friction.mjs
 *
 * Deterministic LangSmith telemetry friction scanner.
 * Queries LangSmith for recent failed runs (error: true), deduplicates against
 * seen runs in state.json, and files standardized GitHub friction issues
 * (two-way-door, agent-ready, complexity:easy) via github-issue-creator so that
 * the local agent daemon (github-doorbell.py) can automatically pick them up and resolve them.
 */

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DEFAULT_STATE_DIR = path.join(os.homedir(), '.local', 'share', 'telemetry-friction');
const DEFAULT_STATE_FILE = path.join(DEFAULT_STATE_DIR, 'state.json');

export function resolveCreateIssueScript(customPath = null) {
  const candidates = [
    customPath,
    process.env.CREATE_ISSUE_SCRIPT,
    path.join(os.homedir(), '.gemini', 'config', 'skills', 'github-issue-creator', 'scripts', 'create-issue.mjs'),
    path.join(
      os.homedir(),
      '.t3',
      'userdata',
      'providers',
      'antigravity',
      'ac0a3dfd6dddb20962cecff6ee5fe65e19d3923be20e52c5ab52ff877f7e4c32',
      'config',
      'skills',
      'github-issue-creator',
      'scripts',
      'create-issue.mjs'
    ),
  ].filter(Boolean);

  for (const c of candidates) {
    if (fs.existsSync(c)) {
      return c;
    }
  }
  return candidates[0] || null;
}

export function parseArgs(argv = process.argv.slice(2)) {
  const args = {
    dryRun: false,
    limit: 20,
    sinceHours: 24,
    project: process.env.LANGSMITH_PROJECT || 'agent-seat',
    repo: 'bovas85/rig-handover',
    stateFile: DEFAULT_STATE_FILE,
    mockFile: null,
    createIssueScript: null,
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--dry-run') {
      args.dryRun = true;
    } else if (arg === '--limit' && i + 1 < argv.length) {
      args.limit = parseInt(argv[++i], 10) || 20;
    } else if (arg === '--since-hours' && i + 1 < argv.length) {
      args.sinceHours = parseFloat(argv[++i]) || 24;
    } else if (arg === '--project' && i + 1 < argv.length) {
      args.project = argv[++i];
    } else if (arg === '--repo' && i + 1 < argv.length) {
      args.repo = argv[++i];
    } else if (arg === '--state-file' && i + 1 < argv.length) {
      args.stateFile = argv[++i];
    } else if (arg === '--mock-file' && i + 1 < argv.length) {
      args.mockFile = argv[++i];
    } else if (arg === '--create-issue-script' && i + 1 < argv.length) {
      args.createIssueScript = argv[++i];
    }
  }

  return args;
}

export function loadState(stateFilePath) {
  try {
    if (fs.existsSync(stateFilePath)) {
      const data = JSON.parse(fs.readFileSync(stateFilePath, 'utf8'));
      return {
        seen_run_ids: Array.isArray(data.seen_run_ids) ? data.seen_run_ids : [],
        last_harvest: data.last_harvest || null,
      };
    }
  } catch (err) {
    console.warn(`[telemetry-friction] Warning: failed to parse ${stateFilePath}, resetting state:`, err.message);
  }
  return { seen_run_ids: [], last_harvest: null };
}

export function saveState(stateFilePath, state) {
  try {
    const dir = path.dirname(stateFilePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(stateFilePath, JSON.stringify(state, null, 2), 'utf8');
  } catch (err) {
    console.error(`[telemetry-friction] Error saving state to ${stateFilePath}:`, err.message);
  }
}

export function formatErrorSummary(rawError) {
  if (!rawError) return 'Unknown error occurred in run';
  if (typeof rawError === 'string') {
    const firstLine = rawError.split('\n')[0].trim();
    return firstLine.slice(0, 100);
  }
  if (typeof rawError === 'object') {
    const msg = rawError.message || rawError.error || JSON.stringify(rawError);
    return String(msg).split('\n')[0].trim().slice(0, 100);
  }
  return String(rawError).slice(0, 100);
}

export async function fetchFailedRuns({ project, limit, sinceHours, mockFile }) {
  if (mockFile) {
    if (!fs.existsSync(mockFile)) {
      throw new Error(`Mock file not found: ${mockFile}`);
    }
    const content = fs.readFileSync(mockFile, 'utf8');
    const parsed = JSON.parse(content);
    return Array.isArray(parsed) ? parsed : (parsed.runs || []);
  }

  const apiKey = process.env.LANGSMITH_API_KEY;
  if (!apiKey) {
    console.log('[telemetry-friction] LANGSMITH_API_KEY is not configured. Skipping remote fetch.');
    return [];
  }

  const { Client } = await import('langsmith');
  const client = new Client({ apiKey });
  const startTime = new Date(Date.now() - sinceHours * 3600 * 1000);

  const runs = [];
  try {
    for await (const run of client.listRuns({
      projectName: project,
      error: true,
      startTime,
      limit,
    })) {
      runs.push(run);
    }
  } catch (err) {
    console.error(`[telemetry-friction] Failed to query LangSmith runs: ${err.message}`);
  }

  return runs;
}

export function reportFrictionIssue({ run, repo, dryRun, createIssueScript }) {
  const runId = run.id || `mock-${Date.now()}`;
  const runName = run.name || 'agent-run';
  const errSummary = formatErrorSummary(run.error);
  const title = `fix(telemetry): ${runName} - ${errSummary}`.slice(0, 90);

  const errorDetail = typeof run.error === 'string' ? run.error : JSON.stringify(run.error, null, 2);
  const langsmithUrl = `https://smith.langchain.com/o/default/projects/p/${encodeURIComponent(
    run.session_name || 'agent-seat'
  )}?runId=${runId}`;

  const desc = `LangSmith telemetry detected an execution error in run \`${runName}\` (${runId}).\n\n### Error Details\n\`\`\`\n${errorDetail.slice(
    0,
    1500
  )}\n\`\`\`\n\nTrace URL: ${langsmithUrl}\nNeeds clean handling, schema correction, or graceful recovery so future autonomous runs complete without regression.`;

  const whatHappened = `Run '${runName}' encountered an unhandled error: ${errSummary}`;
  const wanted = `Handle this failure cleanly without crashing or hanging, ensuring graceful error recovery.`;

  const scriptPath = resolveCreateIssueScript(createIssueScript);

  if (!scriptPath || !fs.existsSync(scriptPath)) {
    if (dryRun) {
      console.log(
        `[telemetry-friction] (Simulated Dry-Run) create-issue.mjs not found at ${scriptPath}. Simulating dry-run issue creation for run ${runId} on ${repo}.`
      );
      return true;
    }
    console.error(`[telemetry-friction] Error: create-issue.mjs not found at ${scriptPath}`);
    return false;
  }

  const args = [
    scriptPath,
    '--repo', repo,
    '--type', 'friction',
    '--title', title,
    '--desc', desc,
    '--door', 'two-way',
    '--complexity', 'easy',
    '--what-happened', whatHappened,
    '--wanted', wanted,
    '--source-thread', langsmithUrl,
  ];

  if (dryRun) {
    args.push('--dry-run');
  }

  console.log(`[telemetry-friction] Filing issue for run ${runId} on ${repo}...`);
  const res = spawnSync('node', args, { encoding: 'utf8' });

  if (res.error) {
    console.error(`[telemetry-friction] Failed to execute create-issue.mjs:`, res.error);
    return false;
  }

  if (res.status !== 0) {
    console.error(`[telemetry-friction] create-issue.mjs failed with exit code ${res.status}:\n${res.stderr || res.stdout}`);
    return false;
  }

  console.log(res.stdout);
  return true;
}

export async function runHarvest(options = {}) {
  const opts = { ...parseArgs(), ...options };
  const state = loadState(opts.stateFile);

  console.log(`[telemetry-friction] Starting telemetry friction scan (project=${opts.project}, lookback=${opts.sinceHours}h, dryRun=${opts.dryRun})`);

  const runs = await fetchFailedRuns(opts);
  console.log(`[telemetry-friction] Retrieved ${runs.length} error run(s) from telemetry.`);

  let filedCount = 0;
  for (const run of runs) {
    const runId = run.id;
    if (runId && state.seen_run_ids.includes(runId)) {
      console.log(`[telemetry-friction] Run ${runId} already seen. Skipping.`);
      continue;
    }

    const targetRepo = run.extra?.metadata?.repo || opts.repo;
    const ok = reportFrictionIssue({
      run,
      repo: targetRepo,
      dryRun: opts.dryRun,
      createIssueScript: opts.createIssueScript,
    });
    if (ok) {
      filedCount++;
      if (runId && !state.seen_run_ids.includes(runId)) {
        state.seen_run_ids.push(runId);
      }
    }
  }

  state.last_harvest = new Date().toISOString();
  saveState(opts.stateFile, state);

  console.log(`[telemetry-friction] Completed harvest. Filed: ${filedCount} issue(s). Total seen: ${state.seen_run_ids.length}`);
  return { ok: true, filedCount, totalSeen: state.seen_run_ids.length };
}

const isDirectRun = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isDirectRun) {
  runHarvest().catch((err) => {
    console.error('[telemetry-friction] Fatal error during harvest:', err);
    process.exit(1);
  });
}
