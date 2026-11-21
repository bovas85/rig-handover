import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { getTracedGemini } from '../src/observability/gemini.js';
import {
  formatErrorSummary,
  loadState,
  parseArgs,
  runHarvest,
  saveState,
} from '../tools/harvest-telemetry-friction.mjs';

describe('Observability & Gemini Wrapper', () => {
  it('creates a raw GoogleGenAI client when tracing is disabled', () => {
    const client = getTracedGemini({
      apiKey: 'test-key',
      tracingEnabled: false,
    });
    expect(client).toBeDefined();
    expect(client.models).toBeDefined();
    expect(typeof client.models.generateContent).toBe('function');
  });

  it('wraps GoogleGenAI client when tracing is enabled', () => {
    const client = getTracedGemini({
      apiKey: 'test-key',
      tracingEnabled: true,
      tags: ['unit-test'],
      metadata: { env: 'test' },
    });
    expect(client).toBeDefined();
    expect(client.models).toBeDefined();
    expect(typeof client.models.generateContent).toBe('function');
  });
});

describe('Telemetry Friction Harvester', () => {
  let tmpDir: string;
  let tmpStateFile: string;
  let tmpMockFile: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'friction-test-'));
    tmpStateFile = path.join(tmpDir, 'state.json');
    tmpMockFile = path.join(tmpDir, 'mock-runs.json');
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

    // First harvest: should process the run
    const res1 = await runHarvest({
      mockFile: tmpMockFile,
      stateFile: tmpStateFile,
      dryRun: true,
      repo: 'bovas85/rig-handover',
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
    });

    expect(res2.ok).toBe(true);
    expect(res2.filedCount).toBe(0);
    expect(res2.totalSeen).toBe(1);
  });
});
