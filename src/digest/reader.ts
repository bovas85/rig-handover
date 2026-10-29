import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { DigestNight, DigestRow, DigestStatus } from './types.js';

export function readNight(runsDir: string, night: string): DigestNight | null {
  const filePath = join(runsDir, `${night}.jsonl`);
  if (!existsSync(filePath)) {
    return null;
  }

  const content = readFileSync(filePath, 'utf8');
  if (content.trim() === '') {
    return {
      night,
      rows: [],
      badLines: 0,
    };
  }

  const lines = content.split('\n');
  const jobMap = new Map<string, DigestRow>();
  let badLines = 0;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }

    try {
      const parsed = JSON.parse(line);
      if (
        !parsed ||
        typeof parsed !== 'object' ||
        typeof parsed.job !== 'string' ||
        typeof parsed.status !== 'string' ||
        typeof parsed.at !== 'string'
      ) {
        badLines++;
        continue;
      }

      const status = parsed.status as DigestStatus;
      const existing = jobMap.get(parsed.job);

      if (!existing) {
        jobMap.set(parsed.job, {
          job: parsed.job,
          owner: parsed.owner ?? '—',
          runs: 1,
          retries: status === 'retry' ? 1 : 0,
          lastStatus: status,
          lastError: parsed.error ?? null,
          firstTime: parsed.at,
          lastTime: parsed.at,
        });
      } else {
        existing.runs += 1;
        if (status === 'retry') {
          existing.retries += 1;
        }
        existing.lastStatus = status;
        existing.lastError = parsed.error ?? null;
        existing.lastTime = parsed.at;
        if (parsed.owner !== null && parsed.owner !== undefined) {
          existing.owner = parsed.owner;
        }
      }
    } catch {
      badLines++;
    }
  }

  const rows = Array.from(jobMap.values()).sort((a, b) =>
    a.job.localeCompare(b.job),
  );

  return {
    night,
    rows,
    badLines,
  };
}
