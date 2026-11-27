import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  buildLangsmithTraceUrl,
  formatErrorSummary,
  loadState,
  parseArgs,
  resolveCreateIssueScript,
  runHarvest,
  saveState,
} from '../tools/harvest-telemetry-friction.mjs';

describe('Telemetry Friction Harvester', () => {
  let tmpDir: string;
  let tmpStateFile: string;
  let tmpMockFile: string;
  let mockCreateIssueScript: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'friction-test-'));
    tmpStateFile = path.join(tmpDir, 'state.json');
    tmpMockFile = path.join(tmpDir, 'mock-runs.json');
    mockCreateIssueScript = path.join(tmpDir, 'mock-create-issue.mjs');

    // Create a hermetic mock of create-issue.mjs for CI environments
    fs.writeFileSync(
      mockCreateIssueScript,
      `#!/usr/bin/env node
console.log("[DRY-RUN] Mock create-issue.mjs executed successfully with args:", process.argv.slice(2));
process.exit(0);
`,
      'utf8'
    );
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('parses CLI arguments correctly', () => {
    const args = parseArgs(['--dry-run', '--limit', '5', '--project', 'custom-proj', '--since-hours', '12']);
    expect(args.dryRun).toBe(true);
    expect(args.limit).toBe(5);
    expect(args.project).toBe('custom-proj');
    expect(args.sinceHours).toBe(12);
  });

  it('formats error summaries cleanly', () => {
    expect(formatErrorSummary('Error: Connection timed out\n  at socket.js:10')).toBe('Error: Connection timed out');
    expect(formatErrorSummary({ message: 'Validation failed' })).toBe('Validation failed');
    expect(formatErrorSummary(null)).toBe('Unknown error occurred in run');
  });

  it('builds EU and US LangSmith trace URLs matching LANGSMITH_ENDPOINT', () => {
    expect(buildLangsmithTraceUrl('agent-seat', 'run-1', 'https://eu.api.smith.langchain.com')).toBe(
      'https://eu.smith.langchain.com/o/default/projects/p/agent-seat?runId=run-1'
    );
    expect(buildLangsmithTraceUrl('agent-seat', 'run-1', 'https://api.smith.langchain.com')).toBe(
      'https://smith.langchain.com/o/default/projects/p/agent-seat?runId=run-1'
    );
  });

  it('resolves create-issue script from custom path or defaults', () => {
    expect(resolveCreateIssueScript(mockCreateIssueScript)).toBe(mockCreateIssueScript);
  });

  it('loads and saves deduplication state', () => {
    const initial = loadState(tmpStateFile);
    expect(initial.seen_run_ids).toEqual([]);

    saveState(tmpStateFile, { seen_run_ids: ['run-1', 'run-2'], last_harvest: '2026-11-21T00:00:00Z' });
    const loaded = loadState(tmpStateFile);
    expect(loaded.seen_run_ids).toEqual(['run-1', 'run-2']);
    expect(loaded.last_harvest).toBe('2026-11-21T00:00:00Z');
  });

  it('harvests mock failed runs with dry-run and deduplicates subsequent runs', async () => {
    fs.writeFileSync(
      tmpMockFile,
      JSON.stringify([
        {
          id: 'test-run-abc-1',
          name: 'healing-subshell-step',
          error: 'ProcessTimedOutError: Subshell remained open for >20s',
          session_name: 'agent-seat',
        },
      ]),
      'utf8'
    );

    // First harvest: should process the run using hermetic mock script
    const res1 = await runHarvest({
      mockFile: tmpMockFile,
      stateFile: tmpStateFile,
      dryRun: true,
      repo: 'bovas85/rig-handover',
      createIssueScript: mockCreateIssueScript,
    });

    expect(res1.ok).toBe(true);
    expect(res1.filedCount).toBe(1);
    expect(res1.totalSeen).toBe(1);

    // Second harvest with same mock: should skip already seen run
    const res2 = await runHarvest({
      mockFile: tmpMockFile,
      stateFile: tmpStateFile,
      dryRun: true,
      repo: 'bovas85/rig-handover',
      createIssueScript: mockCreateIssueScript,
    });

    expect(res2.ok).toBe(true);
    expect(res2.filedCount).toBe(0);
    expect(res2.totalSeen).toBe(1);
  });

  it('falls back to simulated dry-run if create-issue script is absent', async () => {
    fs.writeFileSync(
      tmpMockFile,
      JSON.stringify([
        {
          id: 'test-run-missing-script-1',
          name: 'missing-script-step',
          error: 'SimulatedError: Script not found on disk',
        },
      ]),
      'utf8'
    );

    const res = await runHarvest({
      mockFile: tmpMockFile,
      stateFile: tmpStateFile,
      dryRun: true,
      repo: 'bovas85/rig-handover',
      createIssueScript: '/nonexistent/path/to/create-issue.mjs',
    });

    expect(res.ok).toBe(true);
    expect(res.filedCount).toBe(1);
  });
});
