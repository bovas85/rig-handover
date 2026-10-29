import { readdirSync } from 'node:fs';
import type { RigConfig } from './config.js';
import { readNight } from './digest/reader.js';
import { lastBeat, type Beat } from './heartbeat.js';

export type NightSummary = {
  night: string;
  ok: number;
  retry: number;
  fail: number;
};

export type Status = {
  adapter: string;
  installed: string;
  lastBeat: Beat | null;
  nights: NightSummary[];
};

// Nights on disk = runs/<YYYY-MM-DD>.jsonl, newest first.
export function nightsOnDisk(runsDir: string): string[] {
  try {
    return readdirSync(runsDir)
      .filter((f) => /^\d{4}-\d{2}-\d{2}\.jsonl$/.test(f))
      .map((f) => f.slice(0, 10))
      .sort()
      .reverse();
  } catch {
    return [];
  }
}

export function readStatus(config: RigConfig): Status {
  const nightDates = nightsOnDisk(config.runsDir);
  const nights: NightSummary[] = nightDates.map((night) => {
    const digest = readNight(config.runsDir, night);
    if (!digest) {
      return { night, ok: 0, retry: 0, fail: 0 };
    }
    const ok = digest.rows.filter((r) => r.lastStatus === 'ok').length;
    const retry = digest.rows.filter(
      (r) => r.retries > 0 || r.lastStatus === 'retry',
    ).length;
    const fail = digest.rows.filter((r) => r.lastStatus === 'fail').length;
    return { night, ok, retry, fail };
  });

  return {
    adapter: config.adapter,
    installed: config.installed,
    lastBeat: lastBeat(),
    nights,
  };
}
