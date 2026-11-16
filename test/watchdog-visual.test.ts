import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('watchdog visual tests & UI fixtures', () => {
  const anomaliesFixture = resolve(process.cwd(), 'tests/fixtures/watchdog_preview_active_anomalies.html');
  const settledFixture = resolve(process.cwd(), 'tests/fixtures/watchdog_preview_settled.html');

  it('renders active anomalies visual fixture with correct styling and layout tokens', () => {
    expect(existsSync(anomaliesFixture)).toBe(true);
    const html = readFileSync(anomaliesFixture, 'utf8');

    // Layout & Theme
    expect(html).toContain('class="dark"');
    expect(html).toContain('T3 & Antigravity Self-Healing Control Center');
    expect(html).toContain('id="host-label"');
    expect(html).toContain('id="live-dot"');

    // KPI Metrics grid & badges
    expect(html).toContain('grid-cols-2 md:grid-cols-5');
    expect(html).toContain('MOCK VALIDATION ACTIVE');
    expect(html).toContain('id="kpi-active-runs"');
    expect(html).toContain('id="kpi-anomalies"');

    // Anomaly cards & badges
    expect(html).toContain('HUNG_SUBSHELL_TASK');
    expect(html).toContain('ZOMBIE_TURN_STATE');
    expect(html).toContain('HEALTHY_RUNNING');
    expect(html).toContain('Root Cause: [backtick_subshell_in_double_quotes]');
    expect(html).toContain('Interrupt & Unstick');

    // Prevention Primitives
    expect(html).toContain('safe-write');
    expect(html).toContain('safe-bg');
    expect(html).toContain('session-hygiene skill');
  });

  it('renders settled visual fixture with all sessions healthy', () => {
    expect(existsSync(settledFixture)).toBe(true);
    const html = readFileSync(settledFixture, 'utf8');

    expect(html).toContain('Zero threads stuck in <code class="mono text-slate-300">running</code> state');
    expect(html).toContain('All T3 Code sessions are settled');
    expect(html).toContain('No watchdog events logged yet');
  });
});
