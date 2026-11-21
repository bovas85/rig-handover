import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { serve } from '@hono/node-server';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createApp } from '../src/app.js';
import {
  ROOT_DIR,
  discoverRoutes,
  performRequest,
  runDoctor,
  runOfflineSmoke,
  validateFeatureMap,
  verifyHealthPayload,
} from '../tools/control-rig.mjs';

const testConfig = {
  adapter: 'shim',
  installed: '2026-10-29T14:06:00+01:00',
  beatEverySeconds: 60,
  runsDir: 'runs',
};

describe('control-rig CLI and helpers', () => {
  let server: ReturnType<typeof serve>;
  let origin: string;

  beforeAll(async () => {
    await new Promise<void>((resolve) => {
      server = serve(
        {
          fetch: createApp(testConfig).fetch,
          port: 0,
          hostname: '127.0.0.1',
        },
        (info: AddressInfo) => {
          origin = `http://127.0.0.1:${info.port}`;
          resolve();
        },
      );
    });
  });

  afterAll(async () => {
    await new Promise<void>((resolve, reject) => {
      server.close((err) => (err ? reject(err) : resolve()));
    });
  });

  it('doctor passes runtime, rig.json, runs/, var/, skills, and feature map checks', () => {
    const result = runDoctor(ROOT_DIR);
    expect(result.ok).toBe(true);
    const names = result.checks.map((c: { name: string }) => c.name);
    expect(names).toEqual(
      expect.arrayContaining([
        'node',
        'pnpm',
        'python3',
        'node_modules',
        'rig_json',
        'runs_dir',
        'var_dir',
        'skills_policy',
        'feature_map',
      ]),
    );
  });

  it('doctor skills_policy allows empty .gemini/skills and .claude/skills but fails when non-empty', () => {
    const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'rig-skills-policy-'));
    try {
      fs.mkdirSync(path.join(tmpRoot, '.agents/skills/control-rig'), { recursive: true });
      fs.mkdirSync(path.join(tmpRoot, '.agents/skills/plan-to-issues'), { recursive: true });
      fs.writeFileSync(path.join(tmpRoot, '.agents/skills/control-rig/SKILL.md'), '# control-rig\n');
      fs.writeFileSync(
        path.join(tmpRoot, '.agents/skills/plan-to-issues/SKILL.md'),
        '# plan-to-issues\n',
      );

      // Empty auto-created harness directories should be allowed
      fs.mkdirSync(path.join(tmpRoot, '.gemini/skills'), { recursive: true });
      fs.mkdirSync(path.join(tmpRoot, '.claude/skills'), { recursive: true });

      const emptyResult = runDoctor(tmpRoot);
      const emptyCheck = emptyResult.checks.find(
        (c: { name: string }) => c.name === 'skills_policy',
      );
      expect(emptyCheck?.ok).toBe(true);

      // Non-empty non-symlink .gemini/skills should fail skills_policy
      fs.mkdirSync(path.join(tmpRoot, '.gemini/skills/copied-skill'), { recursive: true });
      fs.writeFileSync(
        path.join(tmpRoot, '.gemini/skills/copied-skill/SKILL.md'),
        '# copied\n',
      );

      const nonEmptyResult = runDoctor(tmpRoot);
      const nonEmptyCheck = nonEmptyResult.checks.find(
        (c: { name: string }) => c.name === 'skills_policy',
      );
      expect(nonEmptyCheck?.ok).toBe(false);
      expect(nonEmptyCheck?.detail).toContain('.gemini/skills is not a symlink to .agents/skills');
    } finally {
      fs.rmSync(tmpRoot, { recursive: true, force: true });
    }
  });

  it('map --check validates Hono SSR routes and mcp-server/tools/ against features.json', () => {
    const routes = discoverRoutes(ROOT_DIR);
    expect(routes).toEqual(
      expect.arrayContaining([
        '/',
        '/health',
        '/digest/:night',
        '/api/digest/:night',
        '/watchdog',
        '/watchdog/api/status',
        'mcp:watchdog',
      ]),
    );

    const validation = validateFeatureMap(ROOT_DIR);
    expect(validation.ok).toBe(true);
    expect(validation.errors).toEqual([]);
  });

  it('request validates live Hono routes with --contains and status checks', async () => {
    const home = await performRequest({
      method: 'GET',
      targetPath: '/',
      origin,
      contains: '2026-10-28',
    });
    expect(home.ok).toBe(true);
    expect(home.status).toBe(200);
    expect(home.containsMatched).toBe(true);

    const digest = await performRequest({
      method: 'GET',
      targetPath: '/digest/2026-10-28',
      origin,
      contains: '2026-10-28',
    });
    expect(digest.ok).toBe(true);
    expect(digest.status).toBe(200);

    const healthRes = await fetch(`${origin}/health`);
    const healthJson = await healthRes.json();
    const healthVerdict = verifyHealthPayload(healthJson, 'HEAD', ROOT_DIR);
    expect(healthVerdict.ok).toBe(true);
  });

  it('execute runs deterministic offline smoke validation for watchdog.py and remote_worker.py', () => {
    const smoke = runOfflineSmoke(ROOT_DIR);
    expect(smoke.ok).toBe(true);
    expect(smoke.watchdog?.ok).toBe(true);
    expect(smoke.remoteWorker?.ok).toBe(true);
    expect(smoke.remoteWorker?.stdout).toContain('remote_worker_smoke_ok');
  });

  it('CLI login reports explicit n/a no-op and map --check exits 0', () => {
    const cliPath = path.join(ROOT_DIR, 'tools/control-rig.mjs');
    const loginOut = execFileSync('node', [cliPath, 'login', '--json'], {
      cwd: ROOT_DIR,
      encoding: 'utf8',
    });
    const loginPayload = JSON.parse(loginOut);
    expect(loginPayload.ok).toBe(true);
    expect(loginPayload.status).toBe('n/a');

    const mapOut = execFileSync('node', [cliPath, 'map', '--check', '--json'], {
      cwd: ROOT_DIR,
      encoding: 'utf8',
    });
    const mapPayload = JSON.parse(mapOut);
    expect(mapPayload.ok).toBe(true);
  });
});
