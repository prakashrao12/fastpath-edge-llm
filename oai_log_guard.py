#!/usr/bin/env python3
"""
oai_log_guard.py
- Live tail, one-shot scan, or "last error only" for OpenAir logs
- On ERROR/FATAL/etc lines, ask a local Ollama model for triage JSON
- (Optional) auto-run SAFE fix commands from an allowlist

Usage examples:
  # Only the most recent error (fast) then exit
  OLLAMA_MODEL=llama3.2 python3 oai_log_guard.py /var/log/openair.log --last

  # One-shot over the whole file (sequential)
  python3 oai_log_guard.py /var/log/openair.log --once --workers 1

  # Live mode (watch new lines only)
  TAIL_N=0 python3 oai_log_guard.py /var/log/openair.log
"""

import os, re, sys, json, time, shlex, argparse, subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# ======== CONFIG (env-overridable) ========
MODEL        = os.getenv("OLLAMA_MODEL", "llama3.2")
BASE_URL     = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
INCIDENT_DIR = os.getenv("INCIDENT_DIR", "/var/log/oai_incidents")
MAX_CONTEXT  = int(os.getenv("CONTEXT_LINES", "50"))
TAIL_N       = int(os.getenv("TAIL_N", "0"))            # live mode: 0 = only new lines
TIMEOUT_SEC  = int(os.getenv("OLLAMA_TIMEOUT", "120"))  # client read timeout seconds
LAST_WINDOW  = int(os.getenv("WINDOW", "800"))          # --last: tail lines to scan

# Allowed command prefixes (VERY IMPORTANT for safety)
ALLOWLIST = [
    p.strip() for p in os.getenv(
        "ALLOWLIST",
        "systemctl status,systemctl restart,journalctl -u,grep,tail"
    ).split(",") if p.strip()
]

# Trigger on these severities (tune if you want tighter)
LEVEL_RE = re.compile(r"\b(error|fatal|critical|panic|segfault)\b", re.I)

SYSTEM_PROMPT = f"""
You are a senior SRE for OpenAirInterface (OAI) core (AMF/SMF/UPF/NRF/NGAP/NAS/RRC/PFCP).
Given recent log context and a specific error line, return STRICT JSON ONLY with keys:
- incident_summary (string)
- probable_causes (array of strings)
- diagnostics_cmds (array of safe, read-only commands; prefixes allowed: {ALLOWLIST})
- fix_cmds (array of minimal safe commands; prefixes allowed only)
- risk_level ("low"|"medium"|"high")
- need_human_review (boolean)
Rules: output JSON only (no prose/markdown). Prefer reversible fixes. If unsure, set need_human_review=true.
""".strip()

# ======== Helpers ========
def ensure_dirs():
    os.makedirs(INCIDENT_DIR, exist_ok=True)

def ts():
    return time.strftime("%Y%m%d-%H%M%S")

def _gen_prompt(messages):
    """Flatten chat messages to a single prompt for /api/generate."""
    sys_txt = []
    user_txt = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            sys_txt.append(content)
        else:
            user_txt.append(f"{role.upper()}:\n{content}")
    out = ""
    if sys_txt:
        out += "\n".join(sys_txt).strip() + "\n\n"
    out += "You must reply with STRICT JSON only.\n\n" + "\n\n".join(user_txt).strip()
    return out

def post_chat(messages, timeout=TIMEOUT_SEC):
    """
    Use /api/generate with streaming to avoid long blocking reads.
    Accumulates 'response' chunks and returns the concatenated string.
    """
    import json as _json
    payload = {
        "model": MODEL,
        "prompt": _gen_prompt(messages),
        "stream": True,
        "format": "json",                          # nudge strict JSON
        "options": {"num_predict": 256, "temperature": 0.2},
        "keep_alive": "5m",
    }
    with requests.post(f"{BASE_URL}/api/generate", json=payload,
                       stream=True, timeout=(10, max(timeout, 600))) as r:
        r.raise_for_status()
        chunks = []
        for line in r.iter_lines():
            if not line:
                continue
            try:
                chunk = _json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if "response" in chunk:
                chunks.append(chunk["response"])
            if chunk.get("done"):
                break
    return "".join(chunks)

def extract_json(s: str):
    """Be forgiving: strip code fences and grab the largest {...} block."""
    s = s.strip()
    s = re.sub(r"^```json\s*|\s*```$", "", s, flags=re.I | re.M)
    first = s.find("{")
    last  = s.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidate = s[first:last+1]
        return json.loads(candidate)
    # final attempt
    return json.loads(s)

def allowed(cmd: str) -> bool:
    cmd = cmd.strip()
    return any(cmd.startswith(prefix) for prefix in ALLOWLIST)

def run_cmd(cmd: str):
    try:
        parts = shlex.split(cmd)
        p = subprocess.run(parts, capture_output=True, text=True, timeout=180)
        return {"cmd": cmd, "rc": p.returncode, "stdout": p.stdout[-4000:], "stderr": p.stderr[-4000:]}
    except Exception as e:
        return {"cmd": cmd, "rc": -1, "stdout": "", "stderr": str(e)}

def follow_file(path: str):
    """Live mode: follow new lines only (TAIL_N controls backlog)."""
    proc = subprocess.Popen(["tail", "-n", str(TAIL_N), "-F", path],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, universal_newlines=True)
    try:
        for line in iter(proc.stdout.readline, ""):
            yield line.rstrip("\n")
    finally:
        proc.kill()

def scan_file_once(path: str, max_context: int = MAX_CONTEXT):
    """One-shot: iterate entire file collecting error lines + context."""
    buf = deque(maxlen=max_context)
    events = []
    with open(path, "r", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            buf.append(line)
            if LEVEL_RE.search(line):
                events.append((line, list(buf)))
    return events

def tail_lines(path: str, n: int):
    out = subprocess.check_output(["tail", "-n", str(n), path], text=True, errors="replace")
    return out.splitlines()

def last_error_event(path: str, window: int = LAST_WINDOW, max_context: int = MAX_CONTEXT):
    """Return (last_error_line, context_lines) from the last `window` lines."""
    lines = tail_lines(path, window)
    last_idx = None
    for i, line in enumerate(lines):
        if LEVEL_RE.search(line):
            last_idx = i
    if last_idx is None:
        return None
    start = max(0, last_idx - max_context)
    ctx = lines[start:last_idx + 1]
    return (lines[last_idx], ctx)

def handle_error(error_line: str, ctx_lines, auto: bool = False):
    context = "\n".join(ctx_lines)
    base_msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",
         "content": f"Recent log context (latest at end):\n```\n{context}\n```\n\nError line:\n```\n{error_line}\n```"}
    ]

    raw = post_chat(base_msgs)
    try:
        data = extract_json(raw)
    except Exception:
        # Retry once with explicit instruction
        retry_msgs = base_msgs + [
            {"role": "user",
             "content": "Previous reply was invalid JSON. Respond again with a SINGLE, COMPLETE, STRICT JSON object only."}
        ]
        raw = post_chat(retry_msgs)
        data = extract_json(raw)  # if this fails, let it raise

    record = {
        "timestamp": ts(),
        "error_line": error_line,
        "summary": data.get("incident_summary"),
        "causes": data.get("probable_causes", []),
        "diagnostics_cmds": [c for c in data.get("diagnostics_cmds", []) if allowed(c)],
        "fix_cmds": [c for c in data.get("fix_cmds", []) if allowed(c)],
        "risk_level": str(data.get("risk_level", "")).lower(),
        "need_human_review": bool(data.get("need_human_review", True)),
        "auto_ran": False,
        "results": []
    }

    # Run diagnostics (allowed-only)
    for cmd in record["diagnostics_cmds"]:
        record["results"].append(run_cmd(cmd))

    # Auto remediation (very conservative)
    if auto and not record["need_human_review"] and record["risk_level"] == "low":
        for cmd in record["fix_cmds"]:
            record["results"].append(run_cmd(cmd))
        record["auto_ran"] = True

    ensure_dirs()
    fname = os.path.join(INCIDENT_DIR, f"incident_{record['timestamp']}.json")
    with open(fname, "w") as f:
        json.dump(record, f, indent=2)
    print(f"[+] Incident saved: {fname}")

# ======== Main ========
def main():
    ap = argparse.ArgumentParser(description="OpenAir log guard (Ollama-powered).")
    ap.add_argument("log_path", help="Path to the log file.")
    ap.add_argument("--auto", action="store_true", help="Auto-run safe fixes when risk=low & no human review needed.")
    ap.add_argument("--once", action="store_true", help="Scan whole file once (collect all errors) then exit.")
    ap.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", "2")),
                    help="Concurrency for --once (default 2).")
    ap.add_argument("--last", action="store_true", help="Process only the most recent error in the last WINDOW lines, then exit.")
    ap.add_argument("--window", type=int, default=LAST_WINDOW, help="Lines to scan from tail when using --last.")
    args = ap.parse_args()

    if args.last:
        evt = last_error_event(args.log_path, args.window, MAX_CONTEXT)
        if not evt:
            print(f"No error-like lines found in the last {args.window} lines.")
            return
        err, ctx = evt
        print(f"[+] Last error:\n{err}\n[+] Context lines: {len(ctx)}")
        handle_error(err, ctx, auto=args.auto)
        return

    if args.once:
        events = scan_file_once(args.log_path)
        print(f"[+] Found {len(events)} error events")
        if not events:
            return
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(handle_error, line, ctx, args.auto) for line, ctx in events]
            for fut in as_completed(futs):
                fut.result()
        return

    # Live tail
    print(f"[+] Monitoring {args.log_path} | model={MODEL} | auto={args.auto}")
    buf = deque(maxlen=MAX_CONTEXT)
    for line in follow_file(args.log_path):
        buf.append(line)
        if LEVEL_RE.search(line):
            print(f"[!] Error detected: {line}")
            try:
                handle_error(line, list(buf), auto=args.auto)
            except Exception as e:
                print(f"[x] Handler failed: {e}")

if __name__ == "__main__":
    main()
