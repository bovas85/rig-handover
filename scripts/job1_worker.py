import json
import os
import sys
import urllib.request

JOB1_URL = os.environ.get(
    "JOB_URL",
    "https://hq.mega.dev/mcp/job/v1.eyJzdWIiOiI2MDQiLCJhdWQiOiJqb2I6dHdvLXBsYWNlczpqb2ItMSIsImlhdCI6MTc5NDE3NTEwNCwiZXhwIjoxNzk0MjYxNTA0fQ.GePdJH7tjdw__tXj2alqExtCWDUalXsn28c-rGjlvmo"
)

def call_tool(tool_name, arguments, call_id=1):
    print(f"\n==========================================")
    print(f"Calling tool: {tool_name} (ID: {call_id})")
    print(f"Arguments:\n{json.dumps(arguments, indent=2)}")
    print(f"==========================================")
    
    body = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        },
        "id": call_id
    }).encode("utf-8")
    
    req = urllib.request.Request(
        JOB1_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "MegaJobWorker/1.0"
        }
    )
    
    with urllib.request.urlopen(req) as resp:
        raw = resp.read().decode("utf-8")
        
    data = None
    for line in raw.split("\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])
            break
    if data is None:
        data = json.loads(raw)
        
    print(f"Response:\n{json.dumps(data, indent=2)}")
    return data

def parse_step_and_payload(data):
    res = data.get("result", {})
    step = res.get("step") or res.get("token") or res.get("stepToken")
    
    text_content = ""
    for c in res.get("content", []):
        if c.get("type") == "text":
            text_content += c.get("text", "")
            
    parsed_json = None
    if text_content:
        try:
            parsed_json = json.loads(text_content)
            if isinstance(parsed_json, dict) and not step:
                step = parsed_json.get("step") or parsed_json.get("token") or parsed_json.get("stepToken")
        except Exception:
            pass
            
    return res, text_content, parsed_json, step

def main():
    print(f"Starting Job 1 Worker from: {JOB1_URL[:40]}...")
    
    # Step 1: search ops/live for tram-3
    search_data = call_tool("search", {"query": "tram-3", "scope": "ops/live"}, 1)
    res, text_content, parsed_json, step = parse_step_and_payload(search_data)
    
    if not step:
        print("ERROR: No step token returned from search!", file=sys.stderr)
        sys.exit(1)
        
    entries = []
    if isinstance(parsed_json, list):
        entries = parsed_json
    elif isinstance(parsed_json, dict):
        entries = parsed_json.get("entries") or parsed_json.get("results") or parsed_json.get("records") or []
        if not entries and "id" in parsed_json:
            entries = [parsed_json]
            
    print(f"Found {len(entries)} entries in search.")
    entry_id = None
    for e in entries:
        if isinstance(e, dict):
            val_str = json.dumps(e).lower()
            if "tram-3" in val_str or "tram 3" in val_str or "tram_3" in val_str:
                entry_id = e.get("id")
                print(f"Selected entry matching tram-3: {e}")
                break
                
    if not entry_id and entries:
        entry_id = entries[0].get("id")
        print(f"Defaulted to first entry: {entries[0]}")
        
    if not entry_id:
        print("ERROR: Could not find tram-3 entry id!", file=sys.stderr)
        sys.exit(1)
        
    # Step 2: read entry with fields ["date", "time", "clock", "line", "cause"]
    fields = ["date", "time", "clock", "line", "cause"]
    read_data = call_tool("read", {"id": entry_id, "fields": fields, "step": step}, 2)
    res, text_content, parsed_read, step = parse_step_and_payload(read_data)
    
    if not step:
        print("ERROR: No step token returned from read!", file=sys.stderr)
        sys.exit(1)
        
    record = parsed_read if isinstance(parsed_read, dict) else {}
    if "fields" in record and isinstance(record["fields"], dict):
        record = record["fields"]
    elif "entry" in record and isinstance(record["entry"], dict):
        record = record["entry"]
    elif "record" in record and isinstance(record["record"], dict):
        record = record["record"]
        
    # Format one line per field you read, as field: value
    formatted_lines = []
    for f in fields:
        if f in record:
            formatted_lines.append(f"{f}: {record[f]}")
        else:
            for k, v in record.items():
                if k.lower() == f.lower():
                    formatted_lines.append(f"{f}: {v}")
                    break
                    
    text_to_redact = "\n".join(formatted_lines)
    print(f"Text to redact:\n{text_to_redact}")
    
    # Step 3: redact text
    redact_data = call_tool("redact", {"text": text_to_redact, "step": step}, 3)
    res, text_content, parsed_redact, step = parse_step_and_payload(redact_data)
    
    if not step:
        print("ERROR: No step token returned from redact!", file=sys.stderr)
        sys.exit(1)
        
    redacted_text = text_content
    if isinstance(parsed_redact, dict):
        if "text" in parsed_redact:
            redacted_text = parsed_redact["text"]
        elif "redacted" in parsed_redact:
            redacted_text = parsed_redact["redacted"]
        elif "result" in parsed_redact:
            redacted_text = parsed_redact["result"]
            
    print(f"Redacted text returned:\n{redacted_text}")
    
    # Step 4: submit exactly the text redact returned, with skillVersion: "1"
    submit_data = call_tool("submit", {
        "result": redacted_text,
        "skillVersion": "1",
        "step": step
    }, 4)
    res, text_content, parsed_submit, final_step = parse_step_and_payload(submit_data)
    
    receipt = res.get("receipt")
    result = res.get("result")
    if isinstance(parsed_submit, dict):
        receipt = receipt or parsed_submit.get("receipt")
        result = result or parsed_submit.get("result")
        
    if not receipt and text_content:
        import re
        m = re.search(r"receipt['\":\s]+([a-zA-Z0-9_\-]+)", text_content)
        if m:
            receipt = m.group(1)
            
    print("\n==========================================")
    print("JOB 1 COMPLETED SUCCESSFULLY!")
    print(f"::RECEIPT_START::{receipt}::RECEIPT_END::")
    print(f"::RESULT_START::{result or redacted_text}::RESULT_END::")
    print(f"::FULL_SUBMIT_START::{json.dumps(submit_data)}::FULL_SUBMIT_END::")
    print("==========================================")
    
    with open("job1_output.json", "w") as f:
        json.dump({
            "receipt": receipt,
            "result": result or redacted_text,
            "raw_record": record,
            "submit_response": submit_data
        }, f, indent=2)

if __name__ == "__main__":
    main()
