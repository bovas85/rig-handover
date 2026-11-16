import os
import re
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHDOG_HTML_PATH = REPO_ROOT / "mcp-server" / "static" / "watchdog.html"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


class TestWatchdogVisual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        cls.html_template = WATCHDOG_HTML_PATH.read_text(encoding="utf-8")

    def _generate_hydrated_html(self, mock_data: dict) -> str:
        """Injects mockData into watchdog.html and populates DOM containers with rendered mock state."""
        harness = """
        class Document {
            constructor() {
                this.elements = new Map();
            }
            getElementById(id) {
                if (!this.elements.has(id)) {
                    this.elements.set(id, {
                        id,
                        innerHTML: '',
                        textContent: '',
                        className: '',
                        value: '',
                        checked: false,
                        classList: { add: () => {}, remove: () => {}, contains: () => false }
                    });
                }
                return this.elements.get(id);
            }
        }
        const document = new Document();
        const localStorage = { getItem: () => '', setItem: () => {}, removeItem: () => {} };
        const FIXED_NOW = new Date('2026-11-16T08:00:00Z').getTime();
        Date.now = () => FIXED_NOW;
        """
        # Read the functions from watchdog.html
        script_matches = re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", self.html_template, re.DOTALL)
        clean_js = "\n".join(script_matches)
        clean_js = re.sub(r"\n\s*refreshAll\(\);", "\n// refreshAll();", clean_js)
        clean_js = re.sub(r"\n\s*setInterval\([^)]+\);", "\n// setInterval(...);", clean_js)

        eval_script = harness + clean_js + f"""
        const mockData = {json.dumps(mock_data)};
        renderDashboard(mockData);
        console.log(JSON.stringify({{
            activeRunsHtml: document.getElementById("active-runs-container").innerHTML,
            eventsHtml: document.getElementById("events-container").innerHTML,
            primitivesHtml: document.getElementById("primitives-container").innerHTML,
            threadsHtml: document.getElementById("threads-tbody").innerHTML,
            kpiActiveRuns: document.getElementById("kpi-active-runs").textContent,
            kpiAnomalies: document.getElementById("kpi-anomalies").textContent,
        }}));
        """
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
            tf.write(eval_script)
            tf_path = tf.name

        try:
            res = subprocess.run(["node", tf_path], capture_output=True, text=True)
            if res.returncode == 0:
                rendered = json.loads(res.stdout)
                html = self.html_template
                html = html.replace('<div class="text-sm text-slate-500 py-4 text-center">Loading active runs...</div>', rendered["activeRunsHtml"])
                html = html.replace('<div class="text-sm text-slate-500 py-4 text-center">Loading events...</div>', rendered["eventsHtml"])
                html = html.replace('<div id="primitives-container" class="grid grid-cols-1 md:grid-cols-3 gap-3"></div>', f'<div id="primitives-container" class="grid grid-cols-1 md:grid-cols-3 gap-3">{rendered["primitivesHtml"]}</div>')
                html = html.replace('<tbody id="threads-tbody" class="divide-y divide-slate-800/70"></tbody>', f'<tbody id="threads-tbody" class="divide-y divide-slate-800/70">{rendered["threadsHtml"]}</tbody>')
                html = html.replace('<div class="text-2xl font-bold text-white mt-2" id="kpi-active-runs">0</div>', f'<div class="text-2xl font-bold text-white mt-2" id="kpi-active-runs">{rendered["kpiActiveRuns"]}</div>')
                html = html.replace('<div class="text-2xl font-bold text-emerald-400 mt-2" id="kpi-anomalies">0</div>', f'<div class="text-2xl font-bold text-rose-400 mt-2" id="kpi-anomalies">{rendered["kpiAnomalies"]}</div>')
                if mock_data.get("snapshot", {}).get("is_mock"):
                    html = html.replace('<span id="mock-badge" class="hidden', '<span id="mock-badge" class="')
                return html
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

        return self.html_template

    def test_generate_and_validate_anomalies_visual_fixture(self):
        mock_data = {
            "status": "ok",
            "snapshot": {
                "is_mock": True,
                "config": {
                    "auto_heal_subshells": True,
                    "auto_interrupt_threads": False,
                    "auto_heal_enabled": True,
                    "axiom_configured": True,
                    "axiom_dataset": "t3-agent-watchdog",
                    "enable_add_validation_tests_and": True,
                },
                "summary": {
                    "active_runs_count": 3,
                    "anomalies_count": 2,
                    "hung_subshells_count": 1,
                    "recent_threads_count": 3,
                },
                "active_runs": [
                    {
                        "run_id": "r-anomaly-1",
                        "thread_id": "cf7eb38b-1234",
                        "title": "Autonomous PR Reviewer",
                        "ordinal": 4,
                        "provider": "gemini-3.8-flash",
                        "status": "running",
                        "run_age_sec": 340,
                        "diagnosis": "hung_subshell_task",
                        "diagnosis_detail": "Background task task-101 spawned an interactive subshell prompt waiting on stdin.",
                        "can_auto_heal": True,
                        "root_cause": {
                            "root_cause_code": "backtick_subshell_in_double_quotes",
                            "root_cause_summary": "Double-quoted python3 -c contained backticks",
                            "prevention_primitive": "/home/leelium/.local/bin/safe-write <path> << '__SAFE_WRITE_EOF__'",
                        },
                        "brain_transcript": {
                            "last_step_index": 24,
                            "last_step_type": "RUN_COMMAND",
                            "last_step_status": "RUNNING",
                            "last_step_age_sec": 310,
                            "uncompleted_tasks": [{"task_short": "task-101"}],
                        }
                    },
                    {
                        "run_id": "r-anomaly-2",
                        "thread_id": "a90b82fe-5678",
                        "title": "Nightly Run Log Ingestion",
                        "ordinal": 2,
                        "provider": "claude-3-7-sonnet",
                        "status": "running",
                        "run_age_sec": 480,
                        "diagnosis": "zombie_turn_state",
                        "diagnosis_detail": "Planner finished replying 210s ago (step 15), but T3 run #2 is still marked 'running' (stuck 'Thinking...').",
                        "can_auto_heal": True,
                        "root_cause": {
                            "root_cause_code": "orphaned_background_daemon_task",
                            "root_cause_summary": "Earlier background command stayed marked RUNNING",
                            "prevention_primitive": "/home/leelium/.local/bin/safe-bg <logfile> <command>",
                        },
                        "brain_transcript": {
                            "last_step_index": 15,
                            "last_step_type": "PLANNER_RESPONSE",
                            "last_step_status": "DONE",
                            "last_step_age_sec": 210,
                            "uncompleted_tasks": [],
                        }
                    },
                    {
                        "run_id": "r-healthy",
                        "thread_id": "18f7d830-9999",
                        "title": "Status Board Polling",
                        "ordinal": 1,
                        "provider": "gemini-3.8-flash",
                        "status": "running",
                        "run_age_sec": 22,
                        "diagnosis": "healthy_running",
                        "diagnosis_detail": "Session is actively executing.",
                        "can_auto_heal": False,
                        "brain_transcript": {
                            "last_step_index": 8,
                            "last_step_type": "RUN_COMMAND",
                            "last_step_status": "RUNNING",
                            "last_step_age_sec": 3,
                            "uncompleted_tasks": [],
                        }
                    }
                ],
                "primitives": [
                    {
                        "name": "safe-write",
                        "path": "/home/leelium/.local/bin/safe-write",
                        "purpose": "Deterministic file writer from stdin/base64; prevents bash backtick & subshell traps.",
                    },
                    {
                        "name": "safe-bg",
                        "path": "/home/leelium/.local/bin/safe-bg",
                        "purpose": "Detached background process launcher; closes stdin/stdout/stderr pipes so tasks never orphan.",
                    },
                    {
                        "name": "session-hygiene skill",
                        "path": "/home/leelium/.gemini/config/skills/session-hygiene/SKILL.md",
                        "purpose": "Auto-updated agent skill containing root causes and mandatory anti-hang rules.",
                    },
                ],
                "recent_threads": [
                    {
                        "thread_id": "cf7eb38b-1234",
                        "title": "Autonomous PR Reviewer",
                        "latest_run_status": "running",
                        "orphaned_tasks_count": 1,
                        "run_count": 4,
                        "interrupted_count": 1,
                        "cancelled_count": 0,
                        "context_usage": {"usedTokens": 68000, "maxTokens": 1000000},
                        "updated_at": "2026-11-16T07:55:00Z",
                    },
                    {
                        "thread_id": "a90b82fe-5678",
                        "title": "Nightly Run Log Ingestion",
                        "latest_run_status": "running",
                        "orphaned_tasks_count": 0,
                        "run_count": 2,
                        "interrupted_count": 0,
                        "cancelled_count": 0,
                        "context_usage": {"usedTokens": 32000, "maxTokens": 1000000},
                        "updated_at": "2026-11-16T07:50:00Z",
                    },
                    {
                        "thread_id": "18f7d830-9999",
                        "title": "Status Board Polling",
                        "latest_run_status": "running",
                        "orphaned_tasks_count": 0,
                        "run_count": 1,
                        "interrupted_count": 0,
                        "cancelled_count": 0,
                        "context_usage": {"usedTokens": 14000, "maxTokens": 1000000},
                        "updated_at": "2026-11-16T07:58:00Z",
                    }
                ]
            },
            "recent_events": [
                {
                    "_time": "2026-11-16T07:52:10Z",
                    "event_type": "healed_hung_subshell",
                    "severity": "warning",
                    "root_cause_code": "backtick_subshell_in_double_quotes",
                    "root_cause_summary": "Killed hung PID 49102 on pts/1",
                    "prevention_primitive": "/home/leelium/.local/bin/safe-write <path>",
                },
                {
                    "_time": "2026-11-16T07:50:00Z",
                    "event_type": "watchdog_scan",
                    "severity": "info",
                    "reason": "Routine 10s health check: 1 anomaly detected",
                }
            ]
        }

        html = self._generate_hydrated_html(mock_data)
        fixture_path = FIXTURES_DIR / "watchdog_preview_active_anomalies.html"
        fixture_path.write_text(html, encoding="utf-8")
        self.assertTrue(fixture_path.exists())

        # Visual layout checks
        self.assertIn("class=\"dark\"", html)
        self.assertIn("MOCK VALIDATION ACTIVE", html)
        self.assertIn("bg-rose-950 text-rose-300", html)
        self.assertIn("bg-emerald-950 text-emerald-300", html)
        self.assertIn("HUNG_SUBSHELL_TASK", html)
        self.assertIn("ZOMBIE_TURN_STATE", html)
        self.assertIn("HEALTHY_RUNNING", html)

    def test_generate_and_validate_settled_visual_fixture(self):
        mock_data = {
            "status": "ok",
            "snapshot": {
                "is_mock": False,
                "config": {
                    "auto_heal_subshells": True,
                    "auto_interrupt_threads": False,
                    "auto_heal_enabled": True,
                    "axiom_configured": True,
                    "axiom_dataset": "t3-agent-watchdog",
                },
                "summary": {
                    "active_runs_count": 0,
                    "anomalies_count": 0,
                    "hung_subshells_count": 0,
                    "recent_threads_count": 2,
                },
                "active_runs": [],
                "anomalies": [],
                "primitives": [],
                "recent_threads": [
                    {
                        "thread_id": "settled-1",
                        "title": "Completed Digest Pipeline",
                        "latest_run_status": "completed",
                        "orphaned_tasks_count": 0,
                        "run_count": 3,
                        "interrupted_count": 0,
                        "cancelled_count": 0,
                        "context_usage": {"usedTokens": 45000, "maxTokens": 1000000},
                        "updated_at": "2026-11-16T07:40:00Z",
                    }
                ]
            },
            "recent_events": []
        }

        html = self._generate_hydrated_html(mock_data)
        fixture_path = FIXTURES_DIR / "watchdog_preview_settled.html"
        fixture_path.write_text(html, encoding="utf-8")
        self.assertTrue(fixture_path.exists())

        self.assertIn("Zero threads stuck in <code class=\"mono text-slate-300\">running</code> state", html)
        self.assertIn("No watchdog events logged yet", html)


if __name__ == "__main__":
    unittest.main()
