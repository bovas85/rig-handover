import { describe, expect, it } from 'vitest';
import { readNight } from '../src/digest/reader.js';

describe('run log reader', () => {
  it('reads runs/2026-10-28.jsonl with 5 jobs and 1 bad line', () => {
    const digest = readNight('runs', '2026-10-28');
    expect(digest).not.toBeNull();
    expect(digest?.badLines).toBe(1);
    expect(digest?.rows).toHaveLength(5);

    const jobs = digest!.rows.map((r) => r.job);
    expect(jobs).toEqual([
      'digest/render',
      'fixtures/refresh',
      'lane/sync',
      'notes/backup',
      'rig/rotate-logs',
    ]);

    const render = digest!.rows.find((r) => r.job === 'digest/render');
    expect(render?.owner).toBe('—');
    expect(render?.lastStatus).toBe('ok');
    expect(render?.runs).toBe(1);
    expect(render?.retries).toBe(0);

    const fixtures = digest!.rows.find((r) => r.job === 'fixtures/refresh');
    expect(fixtures?.runs).toBe(4);
    expect(fixtures?.retries).toBe(3);
    expect(fixtures?.lastStatus).toBe('ok');

    const backup = digest!.rows.find((r) => r.job === 'notes/backup');
    expect(backup?.lastStatus).toBe('fail');
    expect(backup?.lastError).toBe('quota exceeded');
  });

  it('returns null for missing night', () => {
    const digest = readNight('runs', '1999-01-01');
    expect(digest).toBeNull();
  });
});
