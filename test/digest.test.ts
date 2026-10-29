import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createApp } from '../src/app.js';
import type { DigestRow } from '../src/digest/types.js';

const config = {
  adapter: 'shim',
  installed: '2026-10-29T14:06:00+01:00',
  beatEverySeconds: 60,
  runsDir: 'runs',
};

describe('digest routes', () => {
  let tempRunsDir: string;
  let tempConfig: typeof config;

  beforeAll(() => {
    tempRunsDir = mkdtempSync(join(tmpdir(), 'rig-test-runs-'));
    tempConfig = { ...config, runsDir: tempRunsDir };

    // Empty night
    writeFileSync(join(tempRunsDir, '2026-10-01.jsonl'), '');

    // Night with a bad line
    writeFileSync(
      join(tempRunsDir, '2026-10-02.jsonl'),
      JSON.stringify({
        at: '2026-10-02T01:00:00+01:00',
        job: 'job/one',
        status: 'ok',
        owner: 'rook',
      }) +
        '\nnot-valid-json\n' +
        JSON.stringify({
          at: '2026-10-02T02:00:00+01:00',
          job: 'job/two',
          status: 'fail',
          owner: 'lane-07',
          error: 'boom',
        }) +
        '\n',
    );
  });

  afterAll(() => {
    rmSync(tempRunsDir, { recursive: true, force: true });
  });

  describe('2a. Page (/digest/:night)', () => {
    it('renders /digest/2026-10-28 locally with jobs table', async () => {
      const res = await createApp(config).request('/digest/2026-10-28');
      expect(res.status).toBe(200);
      const html = await res.text();
      expect(html).toContain('digest · 2026-10-28');
      expect(html).toContain('fixtures/refresh');
      expect(html).toContain('notes/backup');
      expect(html).toContain('1 bad line skipped');
    });

    it('returns 404 for a night with no file', async () => {
      const res = await createApp(config).request('/digest/1999-01-01');
      expect(res.status).toBe(404);
    });

    it('renders "nothing ran" for an empty night', async () => {
      const res = await createApp(tempConfig).request('/digest/2026-10-01');
      expect(res.status).toBe(200);
      const html = await res.text();
      expect(html).toContain('nothing ran');
    });

    it('renders the valid rows when a night has a bad line', async () => {
      const res = await createApp(tempConfig).request('/digest/2026-10-02');
      expect(res.status).toBe(200);
      const html = await res.text();
      expect(html).toContain('job/one');
      expect(html).toContain('job/two');
      expect(html).toContain('1 bad line skipped');
    });
  });

  describe('2b. JSON (/api/digest/:night)', () => {
    it('returns rows as JSON matching the page job order for 2026-10-28', async () => {
      const [apiRes, pageRes] = await Promise.all([
        createApp(config).request('/api/digest/2026-10-28'),
        createApp(config).request('/digest/2026-10-28'),
      ]);

      expect(apiRes.status).toBe(200);
      const json = (await apiRes.json()) as DigestRow[];
      const html = await pageRes.text();

      expect(Array.isArray(json)).toBe(true);
      expect(json).toHaveLength(5);

      const jobsInJson = json.map((r) => r.job);
      expect(jobsInJson).toEqual([
        'digest/render',
        'fixtures/refresh',
        'lane/sync',
        'notes/backup',
        'rig/rotate-logs',
      ]);

      // Check order matches in HTML
      let lastIndex = -1;
      for (const job of jobsInJson) {
        const index = html.indexOf(job);
        expect(index).toBeGreaterThan(lastIndex);
        lastIndex = index;
      }
    });

    it('returns 404 for a night with no file', async () => {
      const res = await createApp(config).request('/api/digest/1999-01-01');
      expect(res.status).toBe(404);
    });

    it('returns empty array for an empty night', async () => {
      const res = await createApp(tempConfig).request('/api/digest/2026-10-01');
      expect(res.status).toBe(200);
      expect(await res.json()).toEqual([]);
    });
  });

  describe('2c. Board link', () => {
    it('links both nights on disk to digests with counts', async () => {
      const res = await createApp(config).request('/');
      expect(res.status).toBe(200);
      const html = await res.text();
      expect(html).toContain('href="/digest/2026-10-28"');
      expect(html).toContain('href="/digest/2026-10-27"');
      expect(html).toContain('ok');
      expect(html).toContain('retry');
      expect(html).toContain('fail');
    });
  });
});
