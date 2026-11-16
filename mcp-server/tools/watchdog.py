import os
import re
import glob
import json
import time
import signal
import sqlite3
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from config import load_env
except ImportError:
    try:
        from ..config import load_env
    except ImportError:
        def load_env():
            return dict(os.environ)

T3_STATE_DB = Path(os.path.expanduser("~/.t3/userdata/statev2.sqlite"))
T3_BRAINS_DIR = Path(os.path.expanduser(
    "~/.t3/userdata/providers/antigravity/ac0a3dfd6dddb20962cecff6ee5fe65e19d3923be20e52c5ab52ff877f7e4c32/antigravity-acp/brain"
))
WATCHDOG_STATE_DIR = Path(os.path.expanduser("~/.local/share/t3-watchdog"))
WATCHDOG_LOG_FILE = WATCHDOG_STATE_DIR / "events.jsonl"
WATCHDOG_CONFIG_FILE = WATCHDOG_STATE_DIR / "config.json"
WATCHDOG_T3_TOKEN_FILE = WATCHDOG_STATE_DIR / "t3-mcp-token.txt"
SESSION_HYGIENE_SKILL = Path(os.path.expanduser("~/.gemini/config/skills/session-hygiene/SKILL.md"))

DEFAULT_CONFIG = {
    "auto_heal_subshells": True,       # Process-level: kill interactive stdin bash traps (pts/*)
    "auto_interrupt_threads": False,   # Safe default: NEVER auto-interrupt T3 threads from background daemon
    "auto_heal_enabled": True,         # Master toggle / backward compatibility
    "hung_subshell_threshold_sec": 20,
    "zombie_turn_grace_sec": 120,      # Increased grace period to avoid premature flags
    "stalled_run_threshold_sec": 1800, # 30 minutes instead of 10 min
    "axiom_dataset": "t3-agent-watchdog",
    "enable_add_validation_tests_and": True, # Feature flag toggle per Kent S03 Feasibility Protocol
}


def ensure_state_dir():
    WATCHDOG_STATE_DIR.mkdir(parents=True, exist_ok=True)


def is_feature_flag_enabled() -> bool:
    env = load_env()
    val = env.get("ENABLE_ADD_VALIDATION_TESTS_AND", os.environ.get("ENABLE_ADD_VALIDATION_TESTS_AND"))
    if val is not None:
        return str(val).strip().lower() not in ("false", "0", "no", "off")
    return True


def get_watchdog_config() -> Dict[str, Any]:
    ensure_state_dir()
    cfg = dict(DEFAULT_CONFIG)
    if WATCHDOG_CONFIG_FILE.exists():
        try:
            with open(WATCHDOG_CONFIG_FILE, "r") as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception:
            pass
    # If legacy auto_heal_enabled is False, ensure auto_interrupt_threads is also False
    if not cfg.get("auto_heal_enabled", True):
        cfg["auto_interrupt_threads"] = False

    cfg["enable_add_validation_tests_and"] = is_feature_flag_enabled()

    env = load_env()
    if env.get("AXIOM_API_TOKEN"):
        cfg["axiom_configured"] = True
        cfg["axiom_dataset"] = env.get("AXIOM_DATASET", cfg.get("axiom_dataset", "t3-agent-watchdog"))
        cfg["axiom_org_id"] = env.get("AXIOM_ORG_ID", "")
    else:
        cfg["axiom_configured"] = False
    return cfg


def save_watchdog_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    ensure_state_dir()
    cfg = get_watchdog_config()
    for k in [
        "auto_heal_enabled",
        "auto_heal_subshells",
        "auto_interrupt_threads",
        "hung_subshell_threshold_sec",
        "zombie_turn_grace_sec",
        "stalled_run_threshold_sec",
        "axiom_dataset",
        "enable_add_validation_tests_and",
    ]:
        if k in updates and updates[k] is not None:
            cfg[k] = updates[k]
    # Keep auto_heal_enabled in sync
    if "auto_heal_enabled" in updates and updates["auto_heal_enabled"] is False:
        cfg["auto_interrupt_threads"] = False
    to_save = {k: cfg[k] for k in DEFAULT_CONFIG.keys() if k in cfg}
    with open(WATCHDOG_CONFIG_FILE, "w") as f:
        json.dump(to_save, f, indent=2)

    if "axiom_api_token" in updates and updates["axiom_api_token"] is not None:
        _update_env_file({
            "AXIOM_API_TOKEN": updates["axiom_api_token"].strip(),
            "AXIOM_DATASET": str(updates.get("axiom_dataset") or cfg.get("axiom_dataset") or "t3-agent-watchdog").strip(),
            "AXIOM_ORG_ID": str(updates.get("axiom_org_id") or "").strip(),
        })
    return get_watchdog_config()


def _update_env_file(kv: Dict[str, str]):
    env_path = Path(os.path.expanduser("~/.config/second-brain/mcp-server.env"))
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = f.readlines()
    existing_keys = set()
    new_lines = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in kv:
                new_lines.append(f"{k}={kv[k]}\n")
                existing_keys.add(k)
                continue
        new_lines.append(line)
    for k, v in kv.items():
        if k not in existing_keys:
            new_lines.append(f"{k}={v}\n")
    with open(env_path, "w") as f:
        f.writelines(new_lines)
    os.chmod(env_path, 0o600)


def parse_iso_ts(ts_str: Optional[str]) -> Optional[float]:
    if not ts_str:
        return None
    try:
        s = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def classify_root_cause(
    diagnosis: str,
    cmd_text: str = "",
    uncompleted_tasks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Classifies the exact deterministic root cause of a stuck session or command and returns the prevention primitive."""
    cmd = cmd_text or ""
    tasks = uncompleted_tasks or []
    task_cmds = " ".join(t.get("description", "") for t in tasks)
    combined = f"{cmd}\n{task_cmds}"

    if "<<" in combined and ("EOF" in combined) and ("command not found" in combined or diagnosis == "hung_subshell_process"):
        if re.search(r"python3?\s+-c\s+\"", combined) and "`" in combined:
            return {
                "root_cause_code": "backtick_subshell_in_double_quotes",
                "root_cause_summary": "Double-quoted `python3 -c \"...\"` contained Markdown backticks (`), causing bash command substitution to spawn an interactive subshell on pts/*.",
                "prevention_primitive": "/home/leelium/.local/bin/safe-write <path> << '__SAFE_WRITE_EOF__'",
                "skill_ref": "~/.gemini/config/skills/session-hygiene/SKILL.md",
            }
        return {
            "root_cause_code": "nested_heredoc_early_termination",
            "root_cause_summary": "Outer heredoc delimiter (`EOF`) matched a line inside the payload, terminating the heredoc early and executing Markdown lines in bash.",
            "prevention_primitive": "/home/leelium/.local/bin/safe-write <path> << '__SAFE_WRITE_EOF__'",
            "skill_ref": "~/.gemini/config/skills/session-hygiene/SKILL.md",
        }

    if re.search(r"(python3?|node|bash|sh)\s+-c\s+\"", combined) and ("`" in combined or "$(" in combined):
        return {
            "root_cause_code": "backtick_subshell_in_double_quotes",
            "root_cause_summary": "Unescaped backticks or $() inside double-quoted inline script caused bash to spawn a blocking child subshell.",
            "prevention_primitive": "/home/leelium/.local/bin/safe-write <path> << '__SAFE_WRITE_EOF__'",
            "skill_ref": "~/.gemini/config/skills/session-hygiene/SKILL.md",
        }

    if any(k in combined for k in ("rclone authorize", "rclone config reconnect", "auth-server")):
        return {
            "root_cause_code": "blocking_oauth_listener_daemon",
            "root_cause_summary": "Background OAuth listener (`rclone authorize` / `auth-server`) held open PTY descriptors and orphaned the task.",
            "prevention_primitive": "Direct 1-step synchronous OAuth POST to https://oauth2.googleapis.com/token (see google-drive-uploader/SKILL.md)",
            "skill_ref": "~/.gemini/config/skills/google-drive-uploader/SKILL.md",
        }

    if any(k in combined for k in ("server.py", "uvicorn", "yarn dev", "npm run dev", "http.server")) or (
        diagnosis == "zombie_turn_state" and len(tasks) > 0
    ):
        first_task = tasks[0].get("task_short", "task") if tasks else "task"
        first_desc = (tasks[0].get("description", "")[:80] if tasks else cmd[:80]).strip()
        return {
            "root_cause_code": "orphaned_background_daemon_task",
            "root_cause_summary": f"Earlier background command ({first_task}: `{first_desc}`) stayed marked RUNNING in transcript.jsonl, causing T3 Code to leave subsequent turns stuck in 'Thinking...' after the agent finished replying.",
            "prevention_primitive": "/home/leelium/.local/bin/safe-bg <logfile> <command>",
            "skill_ref": "~/.gemini/config/skills/session-hygiene/SKILL.md",
        }

    if diagnosis == "hung_subshell_process" or diagnosis == "hung_subshell_task":
        return {
            "root_cause_code": "interactive_subshell_stdin_wait",
            "root_cause_summary": "Child process dropped into an interactive shell prompt waiting on pts/* stdin.",
            "prevention_primitive": "Pass `< /dev/null` or use `/home/leelium/.local/bin/safe-bg` / `safe-write`",
            "skill_ref": "~/.gemini/config/skills/session-hygiene/SKILL.md",
        }

    return {
        "root_cause_code": "unsettled_provider_turn",
        "root_cause_summary": "Provider turn finished output in transcript.jsonl without closing the T3 run state.",
        "prevention_primitive": "Automatic settlement via watchdog standalone mcp-client session",
        "skill_ref": "~/.gemini/config/skills/session-hygiene/SKILL.md",
    }


def record_learned_prevention_rule(rc: Dict[str, str], thread_id: Optional[str] = None):
    """Appends newly discovered root-cause signatures to session-hygiene/SKILL.md if not already documented."""
    try:
        if not SESSION_HYGIENE_SKILL.exists():
            return
        code = rc.get("root_cause_code", "")
        if not code:
            return
        content = SESSION_HYGIENE_SKILL.read_text(encoding="utf-8")
        if f"`{code}`" in content:
            return
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        t_ref = f" (thread `{thread_id[:8]}`)" if thread_id else ""
        bullet = (
            f"- **[{date_str}] `{code}`**{t_ref}: {rc.get('root_cause_summary', '')} "
            f"**Prevention:** `{rc.get('prevention_primitive', '')}`.\n"
        )
        with open(SESSION_HYGIENE_SKILL, "a", encoding="utf-8") as f:
            f.write(bullet)
    except Exception:
        pass


def ship_to_axiom(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    env = load_env()
    token = env.get("AXIOM_API_TOKEN", "").strip()
    dataset = env.get("AXIOM_DATASET", "t3-agent-watchdog").strip() or "t3-agent-watchdog"
    org_id = env.get("AXIOM_ORG_ID", "").strip()
    if not token or not events:
        return {"shipped": False, "reason": "No AXIOM_API_TOKEN configured or empty events"}

    url = f"https://api.axiom.co/v1/datasets/{dataset}/ingest"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "t3-self-healing-watchdog/2.0",
    }
    if org_id:
        headers["X-Axiom-Org-Id"] = org_id

    try:
        req = urllib.request.Request(url, data=json.dumps(events).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")
            return {"shipped": True, "status": resp.status, "response": body, "dataset": dataset}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        if e.code == 404:
            try:
                create_req = urllib.request.Request(
                    "https://api.axiom.co/v1/datasets",
                    data=json.dumps({"name": dataset, "description": "T3 Code & Antigravity Self-Healing Watchdog Telemetry"}).encode("utf-8"),
                    headers=headers,
                    method="POST"
                )
                urllib.request.urlopen(create_req, timeout=8).read()
                req2 = urllib.request.Request(url, data=json.dumps(events).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req2, timeout=8) as resp2:
                    body2 = json.loads(resp2.read().decode("utf-8", errors="ignore") or "{}")
                    return {"shipped": True, "status": resp2.status, "response": body2, "dataset": dataset, "created_dataset": True}
            except Exception as ce:
                return {"shipped": False, "error": f"HTTP 404 & auto-create failed: {ce}"}
        return {"shipped": False, "error": f"HTTP {e.code}: {err_body[:200]}"}
    except Exception as e:
        return {"shipped": False, "error": str(e)}


def query_axiom_apl(apl_query: str) -> Dict[str, Any]:
    env = load_env()
    token = env.get("AXIOM_API_TOKEN", "").strip()
    org_id = env.get("AXIOM_ORG_ID", "").strip()
    if not token:
        return {"ok": False, "error": "AXIOM_API_TOKEN is not configured"}

    url = "https://api.axiom.co/v1/datasets/_apl?format=legacy"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if org_id:
        headers["X-Axiom-Org-Id"] = org_id

    try:
        req = urllib.request.Request(url, data=json.dumps({"apl": apl_query}).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "data": json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:300]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def record_watchdog_event(event: Dict[str, Any], custom_log_file: Optional[Path] = None) -> Dict[str, Any]:
    ensure_state_dir()
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "_time": now_iso,
        "host": os.uname().nodename,
        **event,
    }
    target_file = custom_log_file or WATCHDOG_LOG_FILE
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with open(target_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    axiom_res = ship_to_axiom([payload])
    payload["_axiom"] = axiom_res
    return payload


def get_recent_watchdog_events(limit: int = 50, custom_log_file: Optional[Path] = None) -> List[Dict[str, Any]]:
    target_file = custom_log_file or WATCHDOG_LOG_FILE
    if not target_file.exists():
        return []
    lines = []
    with open(target_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
    out = []
    for raw in reversed(lines[-limit:]):
        try:
            out.append(json.loads(raw))
        except Exception:
            pass
    return out


def _get_t3_bin() -> str:
    t3_bin = "/home/leelium/.t3/runtime/versions/0.1.6/t3"
    if not os.path.exists(t3_bin):
        candidates = sorted(glob.glob(os.path.expanduser("~/.t3/runtime/versions/*/t3")))
        if candidates:
            t3_bin = candidates[-1]
    return t3_bin


def _token_has_full_access(tok: str) -> bool:
    try:
        import base64
        payload_b64 = tok.split(".")[0]
        padding = "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8"))
        return claims.get("rtc") == "full-access"
    except Exception:
        return False


def _get_or_mint_standalone_mcp_token(force_refresh: bool = False) -> Optional[str]:
    import base64
    import hashlib
    import secrets
    import urllib.parse

    ensure_state_dir()
    if not force_refresh and WATCHDOG_T3_TOKEN_FILE.exists():
        tok = WATCHDOG_T3_TOKEN_FILE.read_text().strip()
        if tok and _token_has_full_access(tok):
            return tok

    t3_bin = _get_t3_bin()
    base_url = "http://127.0.0.1:3773"
    redirect_uri = "http://127.0.0.1/callback"
    resource_uri = f"{base_url}/mcp"

    try:
        # 1. Register MCP OAuth client
        reg_req = urllib.request.Request(
            f"{base_url}/oauth/mcp/register",
            data=json.dumps({
                "client_name": "t3-watchdog-daemon",
                "redirect_uris": [redirect_uri],
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(reg_req, timeout=8) as resp:
            reg_data = json.loads(resp.read().decode("utf-8"))
        client_id = reg_data["client_id"]

        # 2. Issue one-time pairing code via t3 CLI
        pair_res = subprocess.run(
            [t3_bin, "auth", "pairing", "create", "--label", "t3-watchdog-daemon", "--ttl", "5m", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if pair_res.returncode != 0 or not pair_res.stdout.strip():
            return None
        pairing_code = (json.loads(pair_res.stdout).get("credential") or "").strip()
        if not pairing_code:
            return None

        # 3. Approve full-access via /oauth/mcp/decision with PKCE S256
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")

        dec_req = urllib.request.Request(
            f"{base_url}/oauth/mcp/decision",
            data=json.dumps({
                "authorization": {
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                    "resource": resource_uri,
                },
                "decision": {
                    "_tag": "pairing-code",
                    "access": "full-access",
                    "code": pairing_code,
                },
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(dec_req, timeout=8) as resp:
            dec_data = json.loads(resp.read().decode("utf-8"))
        redirect_to = dec_data.get("redirectTo", "")
        parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_to).query)
        auth_code = (parsed_q.get("code") or [None])[0]
        if not auth_code:
            return None

        # 4. Exchange code for full-access bearer token via /oauth/mcp/token
        token_form = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
            "resource": resource_uri,
        }).encode("utf-8")
        tok_req = urllib.request.Request(
            f"{base_url}/oauth/mcp/token",
            data=token_form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(tok_req, timeout=8) as resp:
            tok_data = json.loads(resp.read().decode("utf-8"))
        tok = (tok_data.get("access_token") or "").strip()
        if tok:
            WATCHDOG_T3_TOKEN_FILE.write_text(tok)
            os.chmod(WATCHDOG_T3_TOKEN_FILE, 0o600)
            return tok
    except Exception:
        pass
    return None


def interrupt_t3_thread(thread_id: str, reason: str) -> Dict[str, Any]:
    t3_bin = _get_t3_bin()
    tok = _get_or_mint_standalone_mcp_token(force_refresh=False)
    if not tok:
        return {"ok": False, "error": "Could not mint standalone mcp-client token via t3 auth session issue"}

    for attempt in range(2):
        env = dict(os.environ)
        env["T3_ACP_MCP_ENDPOINT"] = "http://127.0.0.1:3773/mcp"
        env["T3_ACP_MCP_AUTHORIZATION"] = f"Bearer {tok}"
        try:
            res = subprocess.run(
                [t3_bin, "acp-mcp-call", "t3_thread_interrupt", json.dumps({"threadId": thread_id, "reason": reason})],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                if data.get("isError"):
                    # Refresh token once if session expired/revoked
                    if attempt == 0:
                        tok = _get_or_mint_standalone_mcp_token(force_refresh=True)
                        if tok:
                            continue
                    return {"ok": False, "error": data.get("content")}
                return {"ok": True, "result": data.get("structuredContent") or data}
            return {"ok": False, "error": res.stderr or res.stdout}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Interrupt retries exhausted"}


def inspect_brain_transcript(
    brain_id: str,
    custom_brains_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    brains_dir = custom_brains_dir or T3_BRAINS_DIR
    t_path = brains_dir / brain_id / ".system_generated" / "logs" / "transcript.jsonl"
    if not t_path.exists():
        return {"exists": False}

    running_tasks = {}
    completed_tasks = set()
    last_step = None
    total_steps = 0
    error_steps = 0

    try:
        with open(t_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_steps += 1
                try:
                    row = json.loads(line)
                    last_step = row
                    if row.get("status") == "ERROR":
                        error_steps += 1
                    if row.get("type") == "RUN_COMMAND" and row.get("status") == "RUNNING":
                        content = row.get("content") or ""
                        m = re.search(r"task id: ([^\s]+)", content)
                        if m:
                            tid = m.group(1)
                            task_short = tid.split("/")[-1]
                            log_path = brains_dir / brain_id / ".system_generated" / "tasks" / f"{task_short}.log"
                            desc = content.split("Task Description: ")[-1].split("\nTask logs")[0][:240]
                            running_tasks[tid] = {
                                "task_id": tid,
                                "task_short": task_short,
                                "step_index": row.get("step_index"),
                                "created_at": row.get("created_at"),
                                "created_ts": parse_iso_ts(row.get("created_at")),
                                "description": desc,
                                "log_path": str(log_path),
                            }
                    elif row.get("type") in ("SYSTEM_MESSAGE", "GENERIC"):
                        content = row.get("content") or ""
                        # Mark completed if message indicates completion/exit/cancellation, NOT 'still running' notification
                        is_completion = any(k in content for k in ("finished with result:", "exited with code", "Task failed", "was killed", "cancelled", "killed"))
                        if is_completion and "still running" not in content:
                            for m in re.finditer(r"(?:sender=|Task id\s*[\":]\s*|Task\s+[\"'])([^\s\"']+/task-\d+)", content):
                                completed_tasks.add(m.group(1))
                except Exception:
                    pass
    except Exception as e:
        return {"exists": True, "error": str(e)}

    uncompleted_tasks = []
    now = time.time()
    for tid, tinfo in running_tasks.items():
        if tid not in completed_tasks:
            log_tail = ""
            log_mtime = None
            lp = Path(tinfo["log_path"])
            if lp.exists():
                try:
                    log_mtime = lp.stat().st_mtime
                    with open(lp, "rb") as lf:
                        lf.seek(0, os.SEEK_END)
                        sz = lf.tell()
                        lf.seek(max(0, sz - 600))
                        log_tail = lf.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
            age_sec = round(now - tinfo["created_ts"], 1) if tinfo["created_ts"] else None
            tinfo_copy = dict(tinfo)
            tinfo_copy["age_sec"] = age_sec
            tinfo_copy["log_tail"] = log_tail
            tinfo_copy["log_idle_sec"] = round(now - log_mtime, 1) if log_mtime else age_sec
            tinfo_copy["is_active"] = bool(log_mtime and (now - log_mtime) < 300)
            tinfo_copy["has_subshell_prompt"] = bool(
                re.search(r"\[leelium@[^\]]+\]\$\s*$", log_tail) or "command not found" in log_tail
            )
            uncompleted_tasks.append(tinfo_copy)

    last_step_ts = parse_iso_ts(last_step.get("created_at")) if last_step else None
    last_step_age_sec = round(now - last_step_ts, 1) if last_step_ts else None

    return {
        "exists": True,
        "brain_id": brain_id,
        "total_steps": total_steps,
        "error_steps": error_steps,
        "last_step_index": last_step.get("step_index") if last_step else None,
        "last_step_type": last_step.get("type") if last_step else None,
        "last_step_status": last_step.get("status") if last_step else None,
        "last_step_at": last_step.get("created_at") if last_step else None,
        "last_step_age_sec": last_step_age_sec,
        "last_step_has_tool_calls": bool(last_step.get("tool_calls")) if last_step else False,
        "uncompleted_tasks": uncompleted_tasks,
    }


def scan_hung_harness_processes(mock_ps_output: Optional[str] = None) -> List[Dict[str, Any]]:
    """Finds localharness_external child processes and detects interactive bash subshells waiting on pts."""
    results = []
    if mock_ps_output is not None:
        out = mock_ps_output
    else:
        try:
            out = subprocess.check_output(["ps", "-eo", "pid,ppid,etimes,tty,stat,args"], text=True, timeout=5)
        except Exception:
            return results

    procs = {}
    children_map = {}
    for line in out.strip().splitlines()[1:]:
        parts = line.strip().split(None, 5)
        if len(parts) < 6:
            continue
        pid, ppid, etimes, tty, stat, args = int(parts[0]), int(parts[1]), int(parts[2]), parts[3], parts[4], parts[5]
        procs[pid] = {"pid": pid, "ppid": ppid, "etimes": etimes, "tty": tty, "stat": stat, "args": args}
        children_map.setdefault(ppid, []).append(pid)

    for pid, pinfo in procs.items():
        if "localharness_external" in pinfo["args"]:
            queue = list(children_map.get(pid, []))
            while queue:
                cid = queue.pop(0)
                cinfo = procs.get(cid)
                if not cinfo:
                    continue
                if "acp-mcp-bridge" in cinfo["args"]:
                    continue
                grandchildren = children_map.get(cid, [])
                queue.extend(grandchildren)
                if cinfo["args"].strip() in ("bash", "/bin/bash", "sh", "/bin/sh") and cinfo["tty"].startswith("pts/"):
                    parent = procs.get(cinfo["ppid"], {})
                    rc = classify_root_cause("hung_subshell_process", parent.get("args", ""))
                    results.append({
                        "subshell_pid": cid,
                        "wrapper_pid": cinfo["ppid"],
                        "harness_pid": pid,
                        "tty": cinfo["tty"],
                        "elapsed_sec": cinfo["etimes"],
                        "wrapper_cmd": parent.get("args", "")[:250],
                        "root_cause": rc,
                    })
    return results


def get_sessions_snapshot(
    mock_db_conn: Optional[sqlite3.Connection] = None,
    mock_brains_dir: Optional[Path] = None,
    mock_hung_procs: Optional[List[Dict[str, Any]]] = None,
    mock_active_runs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cfg = get_watchdog_config()
    flag_enabled = cfg.get("enable_add_validation_tests_and", True)
    now = time.time()
    threads = []
    active_runs = []
    anomalies = []

    # If mock_active_runs is explicitly injected in validation test mode
    if flag_enabled and mock_active_runs is not None:
        active_runs = list(mock_active_runs)
        for r in active_runs:
            if r.get("diagnosis") != "healthy_running":
                anomalies.append(r)
        hung_procs = mock_hung_procs if mock_hung_procs is not None else []
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": cfg,
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
            "summary": {
                "active_runs_count": len(active_runs),
                "anomalies_count": len(anomalies),
                "hung_subshells_count": len(hung_procs),
                "recent_threads_count": len(threads),
            },
            "active_runs": active_runs,
            "anomalies": anomalies,
            "hung_processes": hung_procs,
            "recent_threads": threads,
            "is_mock": True,
        }

    brains_dir = (mock_brains_dir if flag_enabled and mock_brains_dir else T3_BRAINS_DIR)
    db_conn = mock_db_conn if (flag_enabled and mock_db_conn is not None) else None

    if db_conn is not None or T3_STATE_DB.exists():
        try:
            if db_conn is not None:
                conn = db_conn
                should_close = False
            else:
                conn = sqlite3.connect(f"file:{T3_STATE_DB}?mode=ro", uri=True, timeout=5)
                should_close = True

            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("SELECT thread_id, payload_json FROM orchestration_v2_projection_provider_threads")
            brain_map = {}
            token_map = {}
            for row in cur.fetchall():
                try:
                    p = json.loads(row["payload_json"])
                    native_id = (p.get("nativeThreadRef") or {}).get("nativeId")
                    if native_id:
                        brain_map[row["thread_id"]] = native_id
                    cu = p.get("contextUsage") or {}
                    if cu.get("usedTokens"):
                        token_map[row["thread_id"]] = cu
                except Exception:
                    pass

            cur.execute("""
                SELECT r.run_id, r.thread_id, r.ordinal, r.provider, r.status, r.requested_at, r.completed_at, r.payload_json,
                       t.title, t.project_id, t.updated_at as thread_updated_at
                FROM orchestration_v2_projection_runs r
                JOIN orchestration_v2_projection_threads t ON r.thread_id = t.thread_id
                WHERE r.status IN ('queued', 'preparing', 'starting', 'running', 'waiting')
                ORDER BY r.requested_at DESC
            """)
            for row in cur.fetchall():
                tid = row["thread_id"]
                brain_id = brain_map.get(tid)
                req_ts = parse_iso_ts(row["requested_at"])
                run_age_sec = round(now - req_ts, 1) if req_ts else None
                b_info = inspect_brain_transcript(brain_id, custom_brains_dir=brains_dir) if brain_id else {"exists": False}

                diagnosis = "healthy_running"
                diagnosis_detail = "Session is actively executing."
                can_auto_heal = False
                root_cause = None

                if b_info.get("exists"):
                    last_type = b_info.get("last_step_type")
                    last_status = b_info.get("last_step_status")
                    last_age = b_info.get("last_step_age_sec") or 0
                    last_step_ts = parse_iso_ts(b_info.get("last_step_at"))
                    has_tools = b_info.get("last_step_has_tool_calls")
                    uncompleted = b_info.get("uncompleted_tasks") or []

                    subshell_tasks = [t for t in uncompleted if t.get("has_subshell_prompt")]
                    active_bg_tasks = [t for t in uncompleted if not t.get("has_subshell_prompt")]

                    is_new_turn_waiting_generation = bool(req_ts and last_step_ts and req_ts > last_step_ts)
                    is_pre_execution_state = row["status"] in ("queued", "preparing", "starting")

                    if subshell_tasks:
                        diagnosis = "hung_subshell_task"
                        diagnosis_detail = f"Background task {subshell_tasks[0]['task_short']} spawned an interactive subshell prompt waiting on stdin."
                        can_auto_heal = True
                        root_cause = classify_root_cause(diagnosis, subshell_tasks[0].get("description", ""), uncompleted)
                    elif active_bg_tasks:
                        diagnosis = "healthy_waiting_background_task"
                        task_desc = active_bg_tasks[0].get("description", "")[:60]
                        diagnosis_detail = f"Actively executing background task {active_bg_tasks[0]['task_short']} ({task_desc})."
                        can_auto_heal = False
                    elif is_pre_execution_state or is_new_turn_waiting_generation:
                        diagnosis = "healthy_running"
                        diagnosis_detail = "Run is queued/starting and awaiting model response tokens."
                        can_auto_heal = False
                    elif (
                        last_type == "PLANNER_RESPONSE"
                        and last_status == "DONE"
                        and not has_tools
                        and row["status"] == "running"
                        and last_age >= cfg["zombie_turn_grace_sec"]
                    ):
                        diagnosis = "zombie_turn_state"
                        diagnosis_detail = (
                            f"Planner finished replying {int(last_age)}s ago (step {b_info.get('last_step_index')}), "
                            f"but T3 run #{row['ordinal']} is still marked '{row['status']}' (stuck 'Thinking...')."
                        )
                        can_auto_heal = True
                        root_cause = classify_root_cause(diagnosis, "", uncompleted)
                    elif (
                        row["status"] == "running"
                        and not is_new_turn_waiting_generation
                        and last_age >= cfg["stalled_run_threshold_sec"]
                    ):
                        diagnosis = "stalled_run"
                        diagnosis_detail = f"No transcript activity for {int(last_age)}s while run is '{row['status']}'."
                        can_auto_heal = True
                        root_cause = classify_root_cause(diagnosis, "", uncompleted)

                run_item = {
                    "run_id": row["run_id"],
                    "thread_id": tid,
                    "title": row["title"],
                    "ordinal": row["ordinal"],
                    "provider": row["provider"],
                    "status": row["status"],
                    "requested_at": row["requested_at"],
                    "run_age_sec": run_age_sec,
                    "brain_id": brain_id,
                    "brain_transcript": b_info,
                    "context_usage": token_map.get(tid),
                    "diagnosis": diagnosis,
                    "diagnosis_detail": diagnosis_detail,
                    "root_cause": root_cause,
                    "can_auto_heal": can_auto_heal,
                }
                active_runs.append(run_item)
                if diagnosis != "healthy_running":
                    anomalies.append(run_item)

            cur.execute("""
                SELECT t.thread_id, t.title, t.default_provider, t.updated_at, t.created_at,
                       (SELECT COUNT(*) FROM orchestration_v2_projection_runs r WHERE r.thread_id = t.thread_id) as run_count,
                       (SELECT COUNT(*) FROM orchestration_v2_projection_runs r WHERE r.thread_id = t.thread_id AND r.status = 'interrupted') as interrupted_count,
                       (SELECT COUNT(*) FROM orchestration_v2_projection_runs r WHERE r.thread_id = t.thread_id AND r.status = 'cancelled') as cancelled_count,
                       (SELECT r.status FROM orchestration_v2_projection_runs r WHERE r.thread_id = t.thread_id ORDER BY r.ordinal DESC LIMIT 1) as latest_run_status
                FROM orchestration_v2_projection_threads t
                WHERE t.deleted_at IS NULL
                ORDER BY t.updated_at DESC
                LIMIT 20
            """)
            for row in cur.fetchall():
                tid = row["thread_id"]
                brain_id = brain_map.get(tid)
                b_summary = inspect_brain_transcript(brain_id, custom_brains_dir=brains_dir) if brain_id else {"exists": False}
                uncompleted = b_summary.get("uncompleted_tasks") or []
                threads.append({
                    "thread_id": tid,
                    "title": row["title"],
                    "provider": row["default_provider"],
                    "updated_at": row["updated_at"],
                    "created_at": row["created_at"],
                    "run_count": row["run_count"],
                    "interrupted_count": row["interrupted_count"],
                    "cancelled_count": row["cancelled_count"],
                    "latest_run_status": row["latest_run_status"] or "idle",
                    "brain_id": brain_id,
                    "orphaned_tasks_count": len(uncompleted),
                    "context_usage": token_map.get(tid),
                })

            if should_close:
                conn.close()
        except Exception as e:
            return {"error": f"Failed reading statev2.sqlite: {e}"}

    hung_procs = mock_hung_procs if (flag_enabled and mock_hung_procs is not None) else scan_hung_harness_processes()
    for hp in hung_procs:
        if hp.get("elapsed_sec", 0) >= cfg["hung_subshell_threshold_sec"]:
            anomalies.append({
                "diagnosis": "hung_subshell_process",
                "diagnosis_detail": f"Interactive subshell PID {hp['subshell_pid']} on {hp['tty']} hung for {hp['elapsed_sec']}s",
                "process": hp,
                "root_cause": hp.get("root_cause"),
                "can_auto_heal": True,
            })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": cfg,
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
        "summary": {
            "active_runs_count": len(active_runs),
            "anomalies_count": len(anomalies),
            "hung_subshells_count": len(hung_procs),
            "recent_threads_count": len(threads),
        },
        "active_runs": active_runs,
        "anomalies": anomalies,
        "hung_processes": hung_procs,
        "recent_threads": threads,
    }


def run_watchdog_check(
    auto_heal: Optional[bool] = None,
    force_heal_thread_id: Optional[str] = None,
    mock_snapshot: Optional[Dict[str, Any]] = None,
    custom_log_file: Optional[Path] = None,
) -> Dict[str, Any]:
    cfg = get_watchdog_config()
    flag_enabled = cfg.get("enable_add_validation_tests_and", True)
    snap = mock_snapshot if (flag_enabled and mock_snapshot is not None) else get_sessions_snapshot()
    actions_taken = []

    heal_subshells = cfg.get("auto_heal_subshells", True)
    auto_interrupt = cfg.get("auto_interrupt_threads", False)

    if auto_heal is False:
        heal_subshells = False
        auto_interrupt = False
    elif auto_heal is True:
        heal_subshells = True

    # 1. Kill hung interactive subshells if threshold exceeded (Process-level: SAFE)
    for hp in snap.get("hung_processes", []):
        if heal_subshells and hp.get("elapsed_sec", 0) >= cfg["hung_subshell_threshold_sec"]:
            wrapper_pid = hp.get("wrapper_pid")
            sub_pid = hp.get("subshell_pid")
            killed = []
            for target_pid in (sub_pid, wrapper_pid):
                if target_pid:
                    try:
                        os.kill(target_pid, signal.SIGKILL)
                        killed.append(target_pid)
                    except ProcessLookupError:
                        pass
                    except Exception:
                        pass
            rc = hp.get("root_cause") or classify_root_cause("hung_subshell_process", hp.get("wrapper_cmd", ""))
            record_learned_prevention_rule(rc)
            ev = record_watchdog_event({
                "event_type": "healed_hung_subshell",
                "severity": "warning",
                "subshell_pid": sub_pid,
                "wrapper_pid": wrapper_pid,
                "killed_pids": killed,
                "tty": hp.get("tty"),
                "elapsed_sec": hp.get("elapsed_sec"),
                "wrapper_cmd": hp.get("wrapper_cmd"),
                "root_cause_code": rc.get("root_cause_code"),
                "root_cause_summary": rc.get("root_cause_summary"),
                "prevention_primitive": rc.get("prevention_primitive"),
            }, custom_log_file=custom_log_file)
            actions_taken.append(ev)

    # 2. Heal zombie / stalled T3 runs or explicitly requested thread
    for run in snap.get("active_runs", []):
        tid = run.get("thread_id")
        diag = run.get("diagnosis")
        should_interrupt = False
        reason = ""

        if force_heal_thread_id and tid == force_heal_thread_id:
            should_interrupt = True
            reason = f"Manual self-heal requested via dashboard/MCP for thread '{run.get('title')}'"
        elif auto_interrupt and diag in ("zombie_turn_state", "stalled_run"):
            if run.get("status") == "running":
                should_interrupt = True
                reason = f"Watchdog auto-heal: {run.get('diagnosis_detail')}"

        if should_interrupt and tid:
            uncompleted = (run.get("brain_transcript") or {}).get("uncompleted_tasks") or []
            rc = run.get("root_cause") or classify_root_cause(diag, "", uncompleted)
            record_learned_prevention_rule(rc, thread_id=tid)
            res = interrupt_t3_thread(tid, reason)
            ev = record_watchdog_event({
                "event_type": "healed_stuck_thread",
                "severity": "warning" if diag != "healthy_running" else "info",
                "thread_id": tid,
                "thread_title": run.get("title"),
                "run_id": run.get("run_id"),
                "run_ordinal": run.get("ordinal"),
                "brain_id": run.get("brain_id"),
                "diagnosis": diag,
                "reason": reason,
                "manual": bool(force_heal_thread_id == tid),
                "root_cause_code": rc.get("root_cause_code"),
                "root_cause_summary": rc.get("root_cause_summary"),
                "prevention_primitive": rc.get("prevention_primitive"),
                "interrupt_result": res,
            }, custom_log_file=custom_log_file)
            actions_taken.append(ev)

    # 3. Record heartbeat telemetry
    summary = snap.get("summary", {})
    heartbeat = {
        "event_type": "watchdog_scan",
        "severity": "info" if not snap.get("anomalies") else "warning",
        "active_runs_count": summary.get("active_runs_count", 0),
        "anomalies_count": summary.get("anomalies_count", 0),
        "hung_subshells_count": summary.get("hung_subshells_count", 0),
        "actions_taken_count": len(actions_taken),
    }
    if actions_taken or snap.get("anomalies") or cfg.get("axiom_configured"):
        record_watchdog_event(heartbeat, custom_log_file=custom_log_file)

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "auto_heal_subshells": heal_subshells,
        "auto_interrupt_threads": auto_interrupt,
        "auto_heal_enabled": heal_subshells,
        "actions_taken": actions_taken,
        "snapshot": snap,
    }


def run_watchdog_mcp_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    action = args.get("action", "status")
    if action == "status":
        snap = get_sessions_snapshot()
        events = get_recent_watchdog_events(limit=15)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"snapshot": snap, "recent_events": events}, indent=2)
            }]
        }
    elif action == "scan_and_heal":
        res = run_watchdog_check(auto_heal=True, force_heal_thread_id=args.get("thread_id"))
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(res, indent=2)
            }]
        }
    elif action == "interrupt_thread":
        tid = args.get("thread_id")
        if not tid:
            return {"isError": True, "content": [{"type": "text", "text": "thread_id is required for interrupt_thread"}]}
        res = run_watchdog_check(auto_heal=False, force_heal_thread_id=tid)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(res, indent=2)
            }]
        }
    elif action == "query_axiom":
        cfg = get_watchdog_config()
        dataset = cfg.get("axiom_dataset", "t3-agent-watchdog")
        apl = args.get("apl") or f"['{dataset}'] | summarize count() by event_type, root_cause_code, severity"
        res = query_axiom_apl(apl)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(res, indent=2)
            }]
        }
    else:
        return {"isError": True, "content": [{"type": "text", "text": f"Unknown watchdog action: {action}"}]}
