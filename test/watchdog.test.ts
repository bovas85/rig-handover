import { describe, expect, it } from 'vitest';
import { createApp } from '../src/app.js';

const config = {
  adapter: 'shim',
  installed: '2026-10-29T14:06:00+01:00',
  beatEverySeconds: 60,
  runsDir: 'runs',
};

describe('watchdog control center routes & feature flag', () => {
  it('serves watchdog.html when feature flag is enabled', async () => {
    delete process.env.ENABLE_ADD_VALIDATION_TESTS_AND;
    const res = await createApp(config).request('/watchdog');
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toContain('T3 & Antigravity Self-Healing Control Center');
    expect(html).toContain('id="active-runs-container"');
    expect(html).toContain('id="events-container"');
  });

  it('serves watchdog api status when feature flag is enabled', async () => {
    delete process.env.ENABLE_ADD_VALIDATION_TESTS_AND;
    const res = await createApp(config).request('/watchdog/api/status');
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.status).toBe('ok');
    expect(data.snapshot.config.enable_add_validation_tests_and).toBe(true);
    expect(Array.isArray(data.snapshot.active_runs)).toBe(true);
  });

  it('safely falls back with 404 when feature flag is disabled', async () => {
    process.env.ENABLE_ADD_VALIDATION_TESTS_AND = 'false';
    const app = createApp(config);
    const resHtml = await app.request('/watchdog');
    expect(resHtml.status).toBe(404);

    const resApi = await app.request('/watchdog/api/status');
    expect(resApi.status).toBe(404);

    delete process.env.ENABLE_ADD_VALIDATION_TESTS_AND;
  });
});
