import os
import re
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHDOG_HTML_PATH = REPO_ROOT / "mcp-server" / "static" / "watchdog.html"


class TestWatchdogUIDOM(unittest.TestCase):
    def setUp(self):
        self.assertTrue(WATCHDOG_HTML_PATH.exists(), f"File {WATCHDOG_HTML_PATH} does not exist")
        self.html_content = WATCHDOG_HTML_PATH.read_text(encoding="utf-8")

    def test_html_contains_all_required_dom_element_ids(self):
        required_ids = [
            "active-runs-container",
            "events-container",
            "primitives-container",
            "threads-tbody",
            "toast-banner",
            "kpi-active-runs",
            "kpi-anomalies",
            "kpi-anomalies-sub",
            "kpi-subshell-heal",
            "kpi-thread-interrupt",
            "kpi-axiom",
            "kpi-axiom-sub",
            "toggle-subshell-heal",
            "toggle-thread-interrupt",
            "host-label",
            "last-updated-label",
            "mock-badge",
            "axiom-dataset",
            "axiom-token",
            "axiom-apl",
            "axiom-query-output",
        ]
        for el_id in required_ids:
            pattern = rf'id=[\"\']{re.escape(el_id)}[\"\']'
            self.assertRegex(
                self.html_content,
                pattern,
                f"Missing required DOM element ID: '{el_id}' in watchdog.html"
            )

    def test_javascript_syntax_validity(self):
        """Extracts JavaScript from <script> tags and runs node -c to verify zero syntax errors."""
        script_matches = re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", self.html_content, re.DOTALL)
        self.assertGreater(len(script_matches), 0, "No inline <script> found in watchdog.html")

        combined_js = "\n".join(script_matches)
        # Verify node -c syntax check passes
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
            tf.write(combined_js)
            tf_path = tf.name

        try:
            res = subprocess.run(["node", "-c", tf_path], capture_output=True, text=True)
            self.assertEqual(
                res.returncode, 0,
                f"JavaScript syntax error in watchdog.html:\n{res.stderr}"
            )
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def _run_node_dom_simulation(self, js_body: str) -> dict:
        """Executes a lightweight JS simulation harness in Node to test renderDashboard and DOM bindings."""
        harness = """
        const { Document } = (function() {
            // Minimal DOM shim for Node testing without external npm packages
            class Element {
                constructor(id, tagName = 'div') {
                    this.id = id;
                    this.tagName = tagName;
                    this.textContent = '';
                    this.innerHTML = '';
                    this.className = '';
                    this._classes = new Set();
                    this.checked = false;
                    this.value = '';
                }
                get classList() {
                    const self = this;
                    return {
                        add(c) { self._classes.add(c); self._sync(); },
                        remove(c) { self._classes.delete(c); self._sync(); },
                        contains(c) { return self._classes.has(c); }
                    };
                }
                _sync() {
                    this.className = Array.from(this._classes).join(' ');
                }
            }
            class Document {
                constructor() {
                    this.elements = new Map();
                }
                getElementById(id) {
                    if (!this.elements.has(id)) {
                        const el = new Element(id);
                        this.elements.set(id, el);
                    }
                    return this.elements.get(id);
                }
            }
            return { Document };
        })();

        const document = new Document();
        const window = {};
        const localStorage = { getItem: () => '', setItem: () => {}, removeItem: () => {} };

        // Extracted script functions
        """ + self._extract_functions_from_html() + """

        // Run user test code
        """ + js_body + """
        """

        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
            tf.write(harness)
            tf_path = tf.name

        try:
            res = subprocess.run(["node", tf_path], capture_output=True, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"Node simulation error:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
            return json.loads(res.stdout)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def _extract_functions_from_html(self) -> str:
        script_matches = re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", self.html_content, re.DOTALL)
        code = "\n".join(script_matches)
        # Remove trailing auto-invocations at the end of the script: refreshAll(); setInterval(...);
        code = re.sub(r"\n\s*refreshAll\(\);", "\n// refreshAll();", code)
        code = re.sub(r"\n\s*setInterval\([^)]+\);", "\n// setInterval(...);", code)
        return code

    def test_render_dashboard_active_runs_mock_execution(self):
        mock_data = {
            "status": "ok",
            "snapshot": {
                "is_mock": True,
                "config": {
                    "auto_heal_subshells": True,
                    "auto_interrupt_threads": False,
                    "axiom_configured": True,
                    "axiom_dataset": "t3-test-dataset",
                },
                "summary": {
                    "active_runs_count": 2,
                    "anomalies_count": 1,
                    "hung_subshells_count": 0,
                    "recent_threads_count": 1,
                },
                "active_runs": [
                    {
                        "run_id": "r-1",
                        "thread_id": "t-healthy",
                        "title": "Healthy Task",
                        "ordinal": 1,
                        "provider": "gemini-3.8-flash",
                        "status": "running",
                        "run_age_sec": 45,
                        "diagnosis": "healthy_running",
                        "diagnosis_detail": "Actively executing tool step",
                        "can_auto_heal": False,
                        "brain_transcript": {
                            "last_step_index": 10,
                            "last_step_type": "PLANNER_RESPONSE",
                            "last_step_status": "DONE",
                            "last_step_age_sec": 5,
                            "uncompleted_tasks": [],
                        }
                    },
                    {
                        "run_id": "r-2",
                        "thread_id": "t-hung",
                        "title": "Hung Subshell Task",
                        "ordinal": 3,
                        "provider": "claude-3-7-sonnet",
                        "status": "running",
                        "run_age_sec": 300,
                        "diagnosis": "hung_subshell_task",
                        "diagnosis_detail": "Task task-42 spawned an interactive subshell prompt",
                        "can_auto_heal": True,
                        "root_cause": {
                            "root_cause_code": "backtick_subshell_in_double_quotes",
                            "prevention_primitive": "/home/leelium/.local/bin/safe-write <path>",
                        },
                        "brain_transcript": {
                            "last_step_index": 5,
                            "last_step_type": "RUN_COMMAND",
                            "last_step_status": "RUNNING",
                            "last_step_age_sec": 290,
                            "uncompleted_tasks": [{"task_short": "task-42"}],
                        }
                    }
                ],
                "primitives": [
                    {"name": "safe-write", "path": "/path/to/safe-write", "purpose": "write cleanly"}
                ],
                "recent_threads": [
                    {
                        "thread_id": "t-healthy-12345678",
                        "title": "Healthy Task",
                        "latest_run_status": "running",
                        "orphaned_tasks_count": 0,
                        "run_count": 1,
                        "interrupted_count": 0,
                        "cancelled_count": 0,
                        "context_usage": {"usedTokens": 45000, "maxTokens": 1000000},
                        "updated_at": "2026-11-16T07:15:00Z",
                    }
                ]
            },
            "recent_events": [
                {
                    "_time": "2026-11-16T07:10:00Z",
                    "event_type": "healed_hung_subshell",
                    "severity": "warning",
                    "root_cause_code": "backtick_subshell_in_double_quotes",
                    "reason": "Killed hung PID 1234",
                    "prevention_primitive": "/home/leelium/.local/bin/safe-write",
                }
            ]
        }

        test_js = f"""
        const mockData = {json.dumps(mock_data)};
        renderDashboard(mockData);

        const activeRunsHtml = document.getElementById("active-runs-container").innerHTML;
        const eventsHtml = document.getElementById("events-container").innerHTML;
        const threadsHtml = document.getElementById("threads-tbody").innerHTML;
        const primitivesHtml = document.getElementById("primitives-container").innerHTML;

        console.log(JSON.stringify({{
            kpiActiveRuns: document.getElementById("kpi-active-runs").textContent,
            kpiAnomalies: document.getElementById("kpi-anomalies").textContent,
            kpiSubshellHeal: document.getElementById("kpi-subshell-heal").textContent,
            kpiThreadInterrupt: document.getElementById("kpi-thread-interrupt").textContent,
            kpiAxiom: document.getElementById("kpi-axiom").textContent,
            mockBadgeHidden: document.getElementById("mock-badge").classList.contains("hidden"),
            activeRunsHtml,
            eventsHtml,
            threadsHtml,
            primitivesHtml,
        }}));
        """
        output = self._run_node_dom_simulation(test_js)

        self.assertEqual(output["kpiActiveRuns"], 2)
        self.assertEqual(output["kpiAnomalies"], 1)
        self.assertEqual(output["kpiSubshellHeal"], "AUTO-KILL ON")
        self.assertEqual(output["kpiThreadInterrupt"], "MANUAL ONLY")
        self.assertEqual(output["kpiAxiom"], "CONNECTED")
        # When is_mock is True, mock-badge should NOT have hidden
        self.assertFalse(output["mockBadgeHidden"])

        # Check Active Runs DOM bindings
        self.assertIn("HEALTHY_RUNNING", output["activeRunsHtml"])
        self.assertIn("HUNG_SUBSHELL_TASK", output["activeRunsHtml"])
        self.assertIn("Hung Subshell Task", output["activeRunsHtml"])
        self.assertIn("Root Cause: [backtick_subshell_in_double_quotes]", output["activeRunsHtml"])
        self.assertIn("Interrupt & Unstick", output["activeRunsHtml"])

        # Check Recent Events DOM bindings
        self.assertIn("healed_hung_subshell", output["eventsHtml"])
        self.assertIn("[backtick_subshell_in_double_quotes]", output["eventsHtml"])
        self.assertIn("Killed hung PID 1234", output["eventsHtml"])

        # Check Recent Threads DOM bindings
        self.assertIn("Healthy Task", output["threadsHtml"])
        self.assertIn("45k / 1000k", output["threadsHtml"])

    def test_render_dashboard_empty_active_runs_mock(self):
        mock_data = {
            "status": "ok",
            "snapshot": {
                "is_mock": False,
                "config": {"auto_heal_subshells": True},
                "summary": {"active_runs_count": 0, "anomalies_count": 0},
                "active_runs": [],
                "recent_threads": [],
                "primitives": [],
            },
            "recent_events": []
        }

        test_js = f"""
        const mockData = {json.dumps(mock_data)};
        renderDashboard(mockData);

        console.log(JSON.stringify({{
            activeRunsHtml: document.getElementById("active-runs-container").innerHTML,
            eventsHtml: document.getElementById("events-container").innerHTML,
            threadsHtml: document.getElementById("threads-tbody").innerHTML,
            mockBadgeHidden: document.getElementById("mock-badge").classList.contains("hidden"),
        }}));
        """
        output = self._run_node_dom_simulation(test_js)

        self.assertIn("Zero threads stuck in <code class=\"mono text-slate-300\">running</code> state", output["activeRunsHtml"])
        self.assertIn("No watchdog events logged yet", output["eventsHtml"])
        self.assertIn("No threads found in database", output["threadsHtml"])
        self.assertTrue(output["mockBadgeHidden"])

    def test_xss_protection_in_rendered_dom(self):
        malicious_data = {
            "status": "ok",
            "snapshot": {
                "active_runs": [{
                    "run_id": "r-xss",
                    "thread_id": "t-xss",
                    "title": "<script>alert('xss')</script>",
                    "diagnosis": "healthy_running",
                    "diagnosis_detail": "<img src=x onerror=alert(1)>",
                    "ordinal": 1,
                    "provider": "gemini",
                }],
                "recent_threads": [],
            },
            "recent_events": [{
                "_time": "2026-11-16T07:00:00Z",
                "event_type": "<script>evil()</script>",
                "reason": "<b>bold</b>",
            }]
        }
        test_js = f"""
        const mockData = {json.dumps(malicious_data)};
        renderDashboard(mockData);
        console.log(JSON.stringify({{
            activeRunsHtml: document.getElementById("active-runs-container").innerHTML,
            eventsHtml: document.getElementById("events-container").innerHTML,
        }}));
        """
        output = self._run_node_dom_simulation(test_js)

        self.assertNotIn("<script>alert('xss')</script>", output["activeRunsHtml"])
        self.assertIn("&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;", output["activeRunsHtml"])
        self.assertNotIn("<script>evil()</script>", output["eventsHtml"])
        self.assertIn("&lt;script&gt;evil()&lt;/script&gt;", output["eventsHtml"])


if __name__ == "__main__":
    unittest.main()
