import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { Hono } from 'hono';
import { loadConfig, type RigConfig } from './config.js';
import { readNight } from './digest/reader.js';
import { lane } from './lane.js';
import { readStatus } from './status.js';
import { DigestView } from './views/digest.js';
import { Layout } from './views/layout.js';
import { StatusBoard } from './views/status.js';

export function createApp(config: RigConfig = loadConfig()) {
  const app = new Hono();

  app.get('/health', (c) => c.json({ ok: true, lane: lane().id }));

  app.get('/', (c) =>
    c.html(
      <Layout title="status" lane={lane()}>
        <StatusBoard status={readStatus(config)} />
      </Layout>,
    ),
  );

  app.get('/digest/:night', (c) => {
    const night = c.req.param('night');
    const digest = readNight(config.runsDir, night);
    if (!digest) {
      return c.text('Not found', 404);
    }
    return c.html(
      <Layout title={`digest · ${night}`} lane={lane()}>
        <DigestView digest={digest} />
      </Layout>,
    );
  });

  app.get('/api/digest/:night', (c) => {
    const night = c.req.param('night');
    const digest = readNight(config.runsDir, night);
    if (!digest) {
      return c.json({ error: 'Not found' }, 404);
    }
    return c.json(digest.rows);
  });

  const enableAddValidationTestsAnd =
    process.env.ENABLE_ADD_VALIDATION_TESTS_AND !== 'false' &&
    process.env.ENABLE_ADD_VALIDATION_TESTS_AND !== '0';

  if (enableAddValidationTestsAnd) {
    app.get('/watchdog', (c) => {
      const htmlPath = resolve(process.cwd(), 'mcp-server/static/watchdog.html');
      if (existsSync(htmlPath)) {
        return c.html(readFileSync(htmlPath, 'utf8'));
      }
      return c.text('Watchdog UI not found', 404);
    });

    app.get('/watchdog/api/status', (c) => {
      return c.json({
        status: 'ok',
        snapshot: {
          config: {
            auto_heal_subshells: true,
            auto_interrupt_threads: false,
            auto_heal_enabled: true,
            axiom_configured: false,
            enable_add_validation_tests_and: true,
          },
          summary: {
            active_runs_count: 0,
            anomalies_count: 0,
            hung_subshells_count: 0,
            recent_threads_count: 0,
          },
          active_runs: [],
          anomalies: [],
          hung_processes: [],
          recent_threads: [],
          primitives: [
            {
              name: 'safe-write',
              path: '/home/leelium/.local/bin/safe-write',
              purpose: 'Deterministic file writer from stdin/base64; prevents bash backtick & subshell traps.',
            },
            {
              name: 'safe-bg',
              path: '/home/leelium/.local/bin/safe-bg',
              purpose: 'Detached background process launcher; closes stdin/stdout/stderr pipes so tasks never orphan.',
            },
            {
              name: 'session-hygiene skill',
              path: '/home/leelium/.gemini/config/skills/session-hygiene/SKILL.md',
              purpose: 'Auto-updated agent skill containing root causes and mandatory anti-hang rules.',
            },
          ],
        },
        recent_events: [],
      });
    });
  }

  return app;
}
