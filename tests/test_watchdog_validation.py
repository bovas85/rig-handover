import os
import sys
import json
import time
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add mcp-server to sys.path so imports work cleanly
REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER_DIR = REPO_ROOT / "mcp-server"
if str(MCP_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER_DIR))

from tools.watchdog import (
    DEFAULT_CONFIG,
    get_watchdog_config,
    save_watchdog_config,
    is_feature_flag_enabled,
    classify_root_cause,
    inspect_brain_transcript,
    scan_hung_harness_processes,
    get_sessions_snapshot,
    run_watchdog_check,
    run_watchdog_mcp_tool,
    record_watchdog_event,
    get_recent_watchdog_events,
    parse_iso_ts,
)


class TestWatchdogConfig(unittest.TestCase):
    def test_default_config_keys(self):
        self.assertTrue(DEFAULT_CONFIG["auto_heal_subshells"])
        self.assertFalse(DEFAULT_CONFIG["auto_interrupt_threads"])
        self.assertEqual(DEFAULT_CONFIG["hung_subshell_threshold_sec"], 20)
        self.assertEqual(DEFAULT_CONFIG["zombie_turn_grace_sec"], 120)
        self.assertTrue(DEFAULT_CONFIG["enable_add_validation_tests_and"])

    def test_feature_flag_env_toggle(self):
        with patch.dict(os.environ, {"ENABLE_ADD_VALIDATION_TESTS_AND": "false"}):
            self.assertFalse(is_feature_flag_enabled())
            cfg = get_watchdog_config()
            self.assertFalse(cfg["enable_add_validation_tests_and"])

        with patch.dict(os.environ, {"ENABLE_ADD_VALIDATION_TESTS_AND": "true"}):
            self.assertTrue(is_feature_flag_enabled())
            cfg = get_watchdog_config()
            self.assertTrue(cfg["enable_add_validation_tests_and"])

    def test_save_and_get_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            with patch("tools.watchdog.WATCHDOG_CONFIG_FILE", cfg_file), \
                 patch("tools.watchdog.WATCHDOG_STATE_DIR", Path(tmpdir)):
                cfg = save_watchdog_config({
                    "hung_subshell_threshold_sec": 45,
                    "auto_interrupt_threads": True,
                })
                self.assertEqual(cfg["hung_subshell_threshold_sec"], 45)
                self.assertTrue(cfg["auto_interrupt_threads"])
                self.assertTrue(cfg_file.exists())


class TestRootCauseClassifier(unittest.TestCase):
    def test_backtick_subshell_in_double_quotes(self):
        cmd = 'python3 -c "import os; `ls -la`"'
        rc = classify_root_cause("hung_subshell_process", cmd)
        self.assertEqual(rc["root_cause_code"], "backtick_subshell_in_double_quotes")
        self.assertIn("safe-write", rc["prevention_primitive"])

    def test_nested_heredoc_early_termination(self):
        cmd = "cat << 'EOF'\nsome text\nEOF\nother text"
        rc = classify_root_cause("hung_subshell_process", cmd)
        self.assertEqual(rc["root_cause_code"], "nested_heredoc_early_termination")

    def test_orphaned_background_daemon_task(self):
        tasks = [{"task_short": "task-42", "description": "python server.py 8000"}]
        rc = classify_root_cause("zombie_turn_state", "", tasks)
        self.assertEqual(rc["root_cause_code"], "orphaned_background_daemon_task")
        self.assertIn("safe-bg", rc["prevention_primitive"])

    def test_blocking_oauth_listener(self):
        cmd = "rclone authorize drive"
        rc = classify_root_cause("hung_subshell_process", cmd)
        self.assertEqual(rc["root_cause_code"], "blocking_oauth_listener_daemon")

    def test_interactive_subshell_stdin_wait(self):
        rc = classify_root_cause("hung_subshell_process", "bash")
        self.assertEqual(rc["root_cause_code"], "interactive_subshell_stdin_wait")

    def test_unsettled_provider_turn(self):
        rc = classify_root_cause("healthy_running", "git status")
        self.assertEqual(rc["root_cause_code"], "unsettled_provider_turn")


class TestTranscriptInspectionWithMocks(unittest.TestCase):
    def test_nonexistent_transcript(self):
        res = inspect_brain_transcript("nonexistent-brain-id")
        self.assertFalse(res["exists"])

    def test_mock_transcript_with_running_and_completed_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain_dir = Path(tmpdir) / "test-brain"
            logs_dir = brain_dir / ".system_generated" / "logs"
            tasks_dir = brain_dir / ".system_generated" / "tasks"
            logs_dir.mkdir(parents=True)
            tasks_dir.mkdir(parents=True)

            # Create task log file with prompt
            task_log = tasks_dir / "task-101.log"
            task_log.write_text("line 1\n[leelium@cachyos-x8664]$ \n")

            transcript_file = logs_dir / "transcript.jsonl"
            lines = [
                json.dumps({
                    "step_index": 1,
                    "type": "USER_INPUT",
                    "status": "DONE",
                    "created_at": "2026-11-16T07:00:00Z"
                }),
                json.dumps({
                    "step_index": 2,
                    "type": "RUN_COMMAND",
                    "status": "RUNNING",
                    "content": "task id: test-brain/task-101\nTask Description: test hung subshell\nTask logs at ...",
                    "created_at": "2026-11-16T07:00:05Z"
                }),
                json.dumps({
                    "step_index": 3,
                    "type": "RUN_COMMAND",
                    "status": "RUNNING",
                    "content": "task id: test-brain/task-102\nTask Description: completed task\nTask logs at ...",
                    "created_at": "2026-11-16T07:00:10Z"
                }),
                json.dumps({
                    "step_index": 4,
                    "type": "SYSTEM_MESSAGE",
                    "status": "DONE",
                    "content": 'Task id "test-brain/task-102" finished with result: ok',
                    "created_at": "2026-11-16T07:00:15Z"
                }),
                json.dumps({
                    "step_index": 5,
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "tool_calls": [],
                    "created_at": "2026-11-16T07:00:20Z"
                }),
            ]
            transcript_file.write_text("\n".join(lines) + "\n")

            res = inspect_brain_transcript("test-brain", custom_brains_dir=Path(tmpdir))
            self.assertTrue(res["exists"])
            self.assertEqual(res["total_steps"], 5)
            self.assertEqual(res["last_step_index"], 5)
            self.assertEqual(res["last_step_type"], "PLANNER_RESPONSE")
            self.assertFalse(res["last_step_has_tool_calls"])

            # task-102 was completed, task-101 was uncompleted and has subshell prompt
            uncompleted = res["uncompleted_tasks"]
            self.assertEqual(len(uncompleted), 1)
            self.assertEqual(uncompleted[0]["task_short"], "task-101")
            self.assertTrue(uncompleted[0]["has_subshell_prompt"])


class TestScanHungHarnessProcessesWithMocks(unittest.TestCase):
    def test_mock_ps_output_detects_subshell(self):
        mock_ps = """
  PID  PPID ELAPSED TTY      STAT ARGS
  100     1     500 ?        Ss   /usr/bin/localharness_external --mode stdio
  200   100     300 pts/1    S    python3 -c "import subprocess; ..."
  300   200     150 pts/1    S+   /bin/bash
  400     1     200 ?        Ss   node /usr/bin/some-server
"""
        results = scan_hung_harness_processes(mock_ps_output=mock_ps)
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res["subshell_pid"], 300)
        self.assertEqual(res["wrapper_pid"], 200)
        self.assertEqual(res["harness_pid"], 100)
        self.assertEqual(res["tty"], "pts/1")
        self.assertEqual(res["elapsed_sec"], 150)


class TestGetSessionsSnapshotWithMocks(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE orchestration_v2_projection_provider_threads (
                thread_id TEXT PRIMARY KEY,
                payload_json TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE orchestration_v2_projection_threads (
                thread_id TEXT PRIMARY KEY,
                title TEXT,
                default_provider TEXT,
                updated_at TEXT,
                created_at TEXT,
                deleted_at TEXT,
                project_id TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE orchestration_v2_projection_runs (
                run_id TEXT PRIMARY KEY,
                thread_id TEXT,
                ordinal INTEGER,
                provider TEXT,
                status TEXT,
                requested_at TEXT,
                completed_at TEXT,
                payload_json TEXT
            )
        """)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_direct_mock_active_runs_injection(self):
        mock_runs = [
            {
                "run_id": "mock-run-1",
                "thread_id": "thread-1",
                "title": "Healthy Task",
                "ordinal": 1,
                "provider": "gemini",
                "status": "running",
                "diagnosis": "healthy_running",
                "diagnosis_detail": "Executing",
                "can_auto_heal": False,
            },
            {
                "run_id": "mock-run-2",
                "thread_id": "thread-2",
                "title": "Stuck Turn",
                "ordinal": 2,
                "provider": "claude",
                "status": "running",
                "diagnosis": "zombie_turn_state",
                "diagnosis_detail": "Planner finished replying 180s ago",
                "can_auto_heal": True,
                "root_cause": {
                    "root_cause_code": "orphaned_background_daemon_task",
                    "prevention_primitive": "/home/leelium/.local/bin/safe-bg",
                },
            },
        ]
        snap = get_sessions_snapshot(mock_active_runs=mock_runs)
        self.assertTrue(snap.get("is_mock"))
        self.assertEqual(snap["summary"]["active_runs_count"], 2)
        self.assertEqual(snap["summary"]["anomalies_count"], 1)
        self.assertEqual(len(snap["active_runs"]), 2)
        self.assertEqual(len(snap["anomalies"]), 1)
        self.assertEqual(snap["anomalies"][0]["run_id"], "mock-run-2")

    def test_mock_sqlite_db_diagnoses_zombie_turn(self):
        cur = self.db.cursor()
        cur.execute(
            "INSERT INTO orchestration_v2_projection_provider_threads VALUES (?, ?)",
            ("t-zombie", json.dumps({"nativeThreadRef": {"nativeId": "brain-zombie"}}))
        )
        cur.execute(
            "INSERT INTO orchestration_v2_projection_threads VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("t-zombie", "Zombie Session", "gemini-3.8-flash", "2026-11-16T07:00:00Z", "2026-11-16T06:50:00Z", None, "p-1")
        )
        # Requested 500 seconds ago
        req_iso = "2026-11-16T07:00:00Z"
        cur.execute(
            "INSERT INTO orchestration_v2_projection_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("r-1", "t-zombie", 1, "gemini-3.8-flash", "running", req_iso, None, "{}")
        )
        self.db.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            brain_dir = Path(tmpdir) / "brain-zombie"
            logs_dir = brain_dir / ".system_generated" / "logs"
            logs_dir.mkdir(parents=True)
            # Last step finished replying 200s ago
            last_ts = "2026-11-16T07:05:00Z"
            line = json.dumps({
                "step_index": 12,
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "tool_calls": [],
                "created_at": last_ts,
            })
            (logs_dir / "transcript.jsonl").write_text(line + "\n")

            with patch("tools.watchdog.time.time", return_value=parse_iso_ts(last_ts) + 250):
                snap = get_sessions_snapshot(mock_db_conn=self.db, mock_brains_dir=Path(tmpdir))
                self.assertEqual(snap["summary"]["active_runs_count"], 1)
                self.assertEqual(snap["summary"]["anomalies_count"], 1)
                run = snap["active_runs"][0]
                self.assertEqual(run["diagnosis"], "zombie_turn_state")
                self.assertTrue(run["can_auto_heal"])


class TestEventsLogAndCheck(unittest.TestCase):
    def test_record_and_get_recent_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test_events.jsonl"
            ev1 = record_watchdog_event({"event_type": "test_1", "severity": "info"}, custom_log_file=log_file)
            ev2 = record_watchdog_event({"event_type": "test_2", "severity": "warning"}, custom_log_file=log_file)

            self.assertEqual(ev1["event_type"], "test_1")
            self.assertEqual(ev2["event_type"], "test_2")

            recent = get_recent_watchdog_events(limit=10, custom_log_file=log_file)
            self.assertEqual(len(recent), 2)
            # Most recent event should be first
            self.assertEqual(recent[0]["event_type"], "test_2")
            self.assertEqual(recent[1]["event_type"], "test_1")

    def test_run_watchdog_check_auto_heal_subshell(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "events.jsonl"
            mock_snapshot = {
                "summary": {"active_runs_count": 0, "anomalies_count": 1, "hung_subshells_count": 1},
                "active_runs": [],
                "anomalies": [],
                "hung_processes": [
                    {
                        "subshell_pid": 999999,
                        "wrapper_pid": 999998,
                        "tty": "pts/2",
                        "elapsed_sec": 35,
                        "wrapper_cmd": 'python3 -c "import os; `ls`"',
                        "root_cause": {
                            "root_cause_code": "backtick_subshell_in_double_quotes",
                            "root_cause_summary": "Unescaped backticks",
                            "prevention_primitive": "/home/leelium/.local/bin/safe-write",
                        }
                    }
                ]
            }
            with patch("tools.watchdog.os.kill") as mock_kill:
                res = run_watchdog_check(auto_heal=True, mock_snapshot=mock_snapshot, custom_log_file=log_file)
                self.assertEqual(len(res["actions_taken"]), 1)
                action = res["actions_taken"][0]
                self.assertEqual(action["event_type"], "healed_hung_subshell")
                self.assertEqual(action["subshell_pid"], 999999)


class TestWatchdogMcpTool(unittest.TestCase):
    def test_status_action(self):
        mock_runs = [{
            "run_id": "r-status",
            "thread_id": "t-1",
            "title": "Status test",
            "diagnosis": "healthy_running",
            "status": "running",
        }]
        with patch("tools.watchdog.get_sessions_snapshot", return_value={"active_runs": mock_runs, "summary": {"active_runs_count": 1}}), \
             patch("tools.watchdog.get_recent_watchdog_events", return_value=[]):
            res = run_watchdog_mcp_tool({"action": "status"})
            self.assertIn("content", res)
            body = json.loads(res["content"][0]["text"])
            self.assertEqual(body["snapshot"]["summary"]["active_runs_count"], 1)

    def test_interrupt_thread_validation(self):
        res = run_watchdog_mcp_tool({"action": "interrupt_thread"})
        self.assertTrue(res.get("isError"))
        self.assertIn("thread_id is required", res["content"][0]["text"])

    def test_unknown_action(self):
        res = run_watchdog_mcp_tool({"action": "invalid_action"})
        self.assertTrue(res.get("isError"))
        self.assertIn("Unknown watchdog action", res["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
