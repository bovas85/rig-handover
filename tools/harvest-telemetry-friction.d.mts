export interface HarvestArgs {
  dryRun: boolean;
  limit: number;
  sinceHours: number;
  project: string;
  repo: string;
  stateFile: string;
  mockFile: string | null;
  createIssueScript?: string | null;
}

export interface HarvestState {
  seen_run_ids: string[];
  last_harvest: string | null;
}

export function resolveCreateIssueScript(customPath?: string | null): string | null;
export function parseArgs(argv?: string[]): HarvestArgs;
export function loadState(stateFilePath: string): HarvestState;
export function saveState(stateFilePath: string, state: HarvestState): void;
export function formatErrorSummary(rawError: unknown): string;
export function buildLangsmithTraceUrl(projectName: string, runId: string, endpoint?: string): string;
export function fetchFailedRuns(options?: {
  project?: string;
  limit?: number;
  sinceHours?: number;
  mockFile?: string | null;
  client?: unknown;
}): Promise<any[]>;
export function reportFrictionIssue(options: {
  run: any;
  repo: string;
  project?: string;
  dryRun?: boolean;
  createIssueScript?: string | null;
}): boolean;
export function runHarvest(options?: Partial<HarvestArgs>): Promise<{
  ok: boolean;
  filedCount: number;
  totalSeen: number;
}>;
