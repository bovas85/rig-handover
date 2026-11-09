#!/usr/bin/env python3
"""
Generic GitHub Actions Remote Worker Executor.
Accepts a base64-encoded JSON payload via WORKER_PAYLOAD_B64 or --payload-b64.

Supported payload modes:
1. "python":
   {"mode": "python", "code": "import urllib.request...", "args": [...]}
   Executes the Python code and captures stdout, stderr, and any dict written to worker_output.json.

2. "shell":
   {"mode": "shell", "command": "curl -I https://..."}
   Executes the shell command and captures stdout, stderr, and exit code.

3. "http":
   {"mode": "http", "url": "https://...", "method": "POST", "headers": {...}, "body": {...}}
   Performs an HTTP request from the remote runner and returns status, headers, and body.

4. "mcp_sequence":
   {"mode": "mcp_sequence", "url": "https://.../mcp", "headers": {...}, "calls": [{"name": "...", "arguments": {...}}]}
   Executes a sequence of JSON-RPC MCP tool calls, automatically threading `step` tokens if returned.
"""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


def run_python_mode(payload):
    code = payload.get("code", "")
    args = payload.get("args", [])
    script_path = "_remote_task.py"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)

    proc = subprocess.run(
        [sys.executable, script_path] + [str(a) for a in args],
        capture_output=True,
        text=True,
    )
    custom_output = None
    if os.path.exists("worker_result.json"):
        try:
            with open("worker_result.json", "r", encoding="utf-8") as f:
                custom_output = json.load(f)
        except Exception as e:
            custom_output = {"_load_error": str(e)}

    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "data": custom_output,
    }


def run_shell_mode(payload):
    command = payload.get("command", "")
    proc = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
    )
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def run_http_mode(payload):
    url = payload["url"]
    method = payload.get("method", "GET").upper()
    headers = payload.get("headers", {})
    if "User-Agent" not in headers:
        headers["User-Agent"] = "GitHubRemoteWorker/1.0"

    body = payload.get("body")
    data_bytes = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data_bytes = json.dumps(body).encode("utf-8")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
        elif isinstance(body, str):
            data_bytes = body.encode("utf-8")

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=payload.get("timeout", 60)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            resp_headers = dict(resp.getheaders())
            parsed = None
            try:
                parsed = json.loads(raw)
            except Exception:
                pass
            return {
                "status": resp.status,
                "url": resp.geturl(),
                "headers": resp_headers,
                "body": parsed if parsed is not None else raw,
            }
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {
            "status": e.code,
            "error": str(e),
            "body": err_body,
        }


def call_mcp_tool(url, headers, name, arguments, call_id):
    req_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "GitHubRemoteWorker/1.0",
    }
    if headers:
        req_headers.update(headers)

    body = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
        },
        "id": call_id,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")

    data = None
    for line in raw.split("\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])
            break
    if data is None:
        data = json.loads(raw)
    return data


def run_mcp_sequence_mode(payload):
    url = payload["url"]
    headers = payload.get("headers", {})
    calls = payload.get("calls", [])
    results = []
    last_step = None

    for idx, c in enumerate(calls, start=1):
        name = c["name"]
        args = dict(c.get("arguments", {}))
        if c.get("inject_step", True) and last_step and "step" not in args:
            args["step"] = last_step

        resp = call_mcp_tool(url, headers, name, args, idx)
        res_obj = resp.get("result", {})
        step = res_obj.get("step") or res_obj.get("token") or res_obj.get("stepToken")

        text_content = ""
        for item in res_obj.get("content", []):
            if item.get("type") == "text":
                text_content += item.get("text", "")

        parsed_text = None
        if text_content:
            try:
                parsed_text = json.loads(text_content)
                if isinstance(parsed_text, dict) and not step:
                    step = (
                        parsed_text.get("step")
                        or parsed_text.get("token")
                        or parsed_text.get("stepToken")
                    )
            except Exception:
                pass

        if step:
            last_step = step

        results.append({
            "call_index": idx,
            "tool": name,
            "response": resp,
            "parsed_text": parsed_text if parsed_text is not None else text_content,
            "step": step,
        })

    return {
        "calls_completed": len(results),
        "last_step": last_step,
        "results": results,
    }


def main():
    b64_input = os.environ.get("WORKER_PAYLOAD_B64", "").strip()
    if len(sys.argv) > 2 and sys.argv[1] == "--payload-b64":
        b64_input = sys.argv[2].strip()

    if not b64_input:
        print("ERROR: Missing WORKER_PAYLOAD_B64", file=sys.stderr)
        sys.exit(1)

    try:
        raw_json = base64.b64decode(b64_input).decode("utf-8")
        payload = json.loads(raw_json)
    except Exception as e:
        print(f"ERROR: Invalid base64 JSON payload: {e}", file=sys.stderr)
        sys.exit(1)

    mode = payload.get("mode", "python")
    start_ts = time.time()

    try:
        if mode == "python":
            res = run_python_mode(payload)
        elif mode == "shell":
            res = run_shell_mode(payload)
        elif mode == "http":
            res = run_http_mode(payload)
        elif mode == "mcp_sequence":
            res = run_mcp_sequence_mode(payload)
        else:
            raise ValueError(f"Unsupported worker mode: {mode}")
        status = "ok"
        error = None
    except Exception as e:
        res = None
        status = "error"
        error = str(e)

    envelope = {
        "status": status,
        "mode": mode,
        "duration_ms": round((time.time() - start_ts) * 1000, 2),
        "error": error,
        "output": res,
    }

    with open("worker_output.json", "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)

    if mode in ("python", "shell") and isinstance(res, dict):
        if res.get("stdout"):
            print("--- WORKER STDOUT ---")
            print(res["stdout"])
        if res.get("stderr"):
            print("--- WORKER STDERR ---", file=sys.stderr)
            print(res["stderr"], file=sys.stderr)

    print(f"::WORKER_OUTPUT_START::{json.dumps(envelope)}::WORKER_OUTPUT_END::")

    if status == "error" or (isinstance(res, dict) and res.get("exit_code", 0) != 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
