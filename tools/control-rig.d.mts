export const ROOT_DIR: string;
export const FEATURES_PATH: string;

export interface CliArgs {
  command: string;
  positionals: string[];
  flags: Record<string, string | boolean>;
}

export interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
  fix: string;
}

export interface DoctorResult {
  ok: boolean;
  checks: DoctorCheck[];
  flags: Record<string, string | boolean>;
}

export interface FeatureEntry {
  route: string;
  feature: string;
  source: string;
  reach: string;
  actions: string[];
  verify: string;
}

export interface FeatureMapValidation {
  ok: boolean;
  errors: string[];
  codeRoutes: string[];
  mappedRoutes: string[];
  entries: FeatureEntry[];
}

export interface RequestOptions {
  method?: string;
  targetPath?: string;
  origin?: string;
  contains?: string;
  data?: unknown;
  dump?: string;
  expectedStatus?: number;
}

export interface RequestResult {
  ok: boolean;
  url: string;
  status: number;
  contains: string | null;
  containsMatched: boolean;
  bytes: number;
  snippet: string;
}

export interface OfflineSmokeResult {
  ok: boolean;
  watchdog: { ok: boolean; result?: unknown; stderr?: string; stdout?: string } | null;
  remoteWorker: { ok: boolean; status: string; stdout: string } | null;
}

export interface HealthVerdict {
  ok: boolean;
  commitSha?: string | null;
  targetSha?: string;
  reason: string;
}

export function parseCliArgs(argv: string[]): CliArgs;
export function normalizeOrigin(origin?: string): string;
export function resolveLocalOrigin(explicitOrigin?: string, rootDir?: string): string;
export function discoverRoutes(rootDir?: string): string[];
export function validateFeatureMap(rootDir?: string, featuresPath?: string): FeatureMapValidation;
export function runDoctor(rootDir?: string, flags?: Record<string, string | boolean>): DoctorResult;
export function performRequest(opts: RequestOptions): Promise<RequestResult>;
export function runOfflineSmoke(rootDir?: string): OfflineSmokeResult;
export function verifyHealthPayload(
  data: { ok?: boolean; lane?: string; commitSha?: string } | null | undefined,
  expectedSha?: string,
  rootDir?: string,
): HealthVerdict;
