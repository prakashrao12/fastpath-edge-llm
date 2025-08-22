from collections import deque
import subprocess
from typing import List, Optional, Tuple
from .parsing import LEVEL_RE, parse_line_to_kv, is_error_level

def follow_file(path: str, tail_n: int):
    """Yield lines from `tail -F`. tail_n=0 => only new lines."""
    proc = subprocess.Popen(["tail", "-n", str(tail_n), "-F", path],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, universal_newlines=True)
    try:
        for line in iter(proc.stdout.readline, ""):
            yield line.rstrip("\n")
    finally:
        proc.kill()

def scan_file_once(path: str, max_context: int):
    """Return list[(error_line, context_lines)] scanning entire file."""
    buf = deque(maxlen=max_context)
    events = []
    with open(path, "r", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            buf.append(line)
            if LEVEL_RE.search(line):
                events.append((line, list(buf)))
    return events

def tail_lines(path: str, n: int) -> List[str]:
    out = subprocess.check_output(["tail", "-n", str(n), path], text=True, errors="replace")
    return out.splitlines()

def last_error_event(path: str, window: int, max_context: int) -> Optional[Tuple[str, list[str]]]:
    lines = tail_lines(path, window)
    last_idx = None
    for i, line in enumerate(lines):
        if LEVEL_RE.search(line):
            last_idx = i
    if last_idx is None:
        return None
    start = max(0, last_idx - max_context)
    return (lines[last_idx], lines[start:last_idx+1])

# JSON input support
import json

def load_events_from_json(json_path: str):
    with open(json_path, "r") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]

def lines_from_events(events) -> List[str]:
    lines = []
    for ev in events:
        ts  = ev.get("ts", "")
        c   = ev.get("component", "UNK")
        lvl = ev.get("level", "INFO")
        msg = ev.get("message", ev.get("msg", ev.get("text", "")))
        line = f"{ts} [{c}] {lvl} {msg}".strip()
        lines.append(line)
    return lines

def last_error_event_from_json(events, max_context: int) -> Optional[Tuple[str, list[str]]]:
    last_idx = None
    for i, ev in enumerate(events):
        if is_error_level(str(ev.get("level", ""))):
            last_idx = i
    if last_idx is None:
        return None
    lines = lines_from_events(events)
    start = max(0, last_idx - max_context)
    ctx = lines[start:last_idx+1]
    return (ctx[-1], ctx)
