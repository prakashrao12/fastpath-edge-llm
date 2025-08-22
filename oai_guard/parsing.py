import re
from typing import Optional, Dict, List

# Coarse severity trigger
LEVEL_RE = re.compile(r"\b(error|fatal|critical|panic|segfault)\b", re.I)

# OAI-ish line pattern:
# 2025-08-08 09:12:25.109 [SMF] ERROR    Message...
LINE_RE = re.compile(r"""
^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\s+
\[(?P<component>[A-Za-z0-9_-]+)\]\s+
(?P<level>INFO|WARN|WARNING|ERROR|CRITICAL|FATAL)\s+
(?P<message>.*)$
""", re.X)

def parse_line_to_kv(line: str) -> Dict:
    m = LINE_RE.search(line)
    if not m:
        return {"raw": line}
    level = m.group("level")
    if level == "WARNING":
        level = "WARN"
    return {
        "ts": m.group("ts"),
        "component": m.group("component"),
        "level": level,
        "message": m.group("message"),
        "raw": line,
    }

def kvs_from_lines(lines: List[str]) -> List[Dict]:
    return [parse_line_to_kv(l) for l in lines]

def is_error_level(level: Optional[str]) -> bool:
    return (level or "").upper() in ("ERROR", "CRITICAL", "FATAL")
