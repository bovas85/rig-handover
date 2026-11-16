import os
import sys
import json
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import remote_worker


class TestRemoteWorkerScript(unittest.TestCase):
    def test_run_python_mode_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                payload = {
                    "mode": "python",
                    "code": "import sys; print('hello remote python', sys.argv[1])",
                    "args": ["arg_val"],
                }
                res = remote_worker.run_python_mode(payload)
                self.assertEqual(res["exit_code"], 0)
                self.assertIn("hello remote python arg_val", res["stdout"])
                self.assertIsNone(res["data"])
            finally:
                os.chdir(old_cwd)

    def test_run_python_mode_custom_data_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                payload = {
                    "mode": "python",
                    "code": """
import json
with open('worker_result.json', 'w') as f:
    json.dump({'status': 'custom_success', 'processed': 42}, f)
""",
                }
                res = remote_worker.run_python_mode(payload)
                self.assertEqual(res["exit_code"], 0)
                self.assertEqual(res["data"], {"status": "custom_success", "processed": 42})
            finally:
                os.chdir(old_cwd)

    def test_run_shell_mode(self):
        payload = {
            "mode": "shell",
            "command": "echo 'remote shell test stdout' && echo 'remote shell test stderr' >&2",
        }
        res = remote_worker.run_shell_mode(payload)
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("remote shell test stdout", res["stdout"])
        self.assertIn("remote shell test stderr", res["stderr"])

    def test_run_http_mode_mocked(self):
        payload = {
            "mode": "http",
            "url": "https://api.example.com/data",
            "method": "POST",
            "headers": {"X-Custom": "test-header"},
            "body": {"query": "sample"},
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"ok": True, "count": 5}).encode("utf-8")
        mock_response.getheaders.return_value = [("Content-Type", "application/json")]
        mock_response.geturl.return_value = "https://api.example.com/data"
        mock_response.status = 200

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            res = remote_worker.run_http_mode(payload)
            self.assertEqual(res["status"], 200)
            self.assertEqual(res["body"], {"ok": True, "count": 5})

    def test_call_mcp_tool_mocked(self):
        mock_response = MagicMock()
        rpc_reply = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "step": "step_token_abc123",
                "content": [{"type": "text", "text": "{\"key\": \"val\"}"}]
            }
        }
        mock_response.read.return_value = (f"data: {json.dumps(rpc_reply)}\n").encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            resp = remote_worker.call_mcp_tool(
                url="https://example.com/mcp",
                headers={"Authorization": "Bearer test"},
                name="sample_tool",
                arguments={"arg": 1},
                call_id=1,
            )
            self.assertEqual(resp["result"]["step"], "step_token_abc123")

    def test_run_mcp_sequence_mode_threading_step(self):
        payload = {
            "mode": "mcp_sequence",
            "url": "https://example.com/mcp",
            "headers": {},
            "calls": [
                {"name": "tool_1", "arguments": {"q": "search"}},
                {"name": "tool_2", "arguments": {"id": "item-1"}, "inject_step": True},
            ]
        }

        call_records = []
        def mock_call_tool(url, headers, name, arguments, call_id):
            call_records.append((name, dict(arguments)))
            step_token = f"step_{call_id}"
            return {
                "jsonrpc": "2.0",
                "id": call_id,
                "result": {
                    "step": step_token,
                    "content": [{"type": "text", "text": f"result for {name}"}]
                }
            }

        with patch("remote_worker.call_mcp_tool", side_effect=mock_call_tool):
            res = remote_worker.run_mcp_sequence_mode(payload)
            self.assertEqual(res["calls_completed"], 2)
            self.assertEqual(res["last_step"], "step_2")
            # First tool has no injected step; second tool receives step_1 from tool_1
            self.assertNotIn("step", call_records[0][1])
            self.assertEqual(call_records[1][1].get("step"), "step_1")

    def test_main_cli_payload(self):
        payload = {
            "mode": "python",
            "code": "print('cli execution successful')",
        }
        b64_payload = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch.object(sys, "argv", ["remote_worker.py", "--payload-b64", b64_payload]):
                    with patch("builtins.print") as mock_print:
                        remote_worker.main()
                        self.assertTrue(os.path.exists("worker_output.json"))
                        with open("worker_output.json", "r") as f:
                            out = json.load(f)
                            self.assertEqual(out["status"], "ok")
                            self.assertEqual(out["mode"], "python")
                            self.assertIn("cli execution successful", out["output"]["stdout"])
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
