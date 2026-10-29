export type DigestStatus = 'ok' | 'retry' | 'fail';

export type DigestRow = {
  job: string;
  owner: string;
  runs: number;
  retries: number;
  lastStatus: DigestStatus;
  lastError: string | null;
  firstTime: string;
  lastTime: string;
};

export type DigestNight = {
  night: string;
  rows: DigestRow[];
  badLines: number;
};

export type ReadNight = (runsDir: string, night: string) => DigestNight | null;
