# oai_guard/history.py
import os, re, json, sqlite3, hashlib
from dataclasses import dataclass, field

DB_PATH = os.getenv("HISTORY_DB", "/var/log/oai_incidents/triage_cache.sqlite3")

_SIG_TS = re.compile(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3}\s+')
_SIG_IP = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_SIG_HEX = re.compile(r'0x[0-9A-Fa-f]+')
_SIG_NUM = re.compile(r'\b\d+\b')
_SIG_SQ  = re.compile(r"'[^']+'")
_SIG_DQ  = re.compile(r'"[^"]+"')

def make_signature(line: str) -> str:
    """Normalize volatile parts so similar errors map to same signature."""
    x = _SIG_TS.sub('', line)
    x = _SIG_IP.sub('<IP>', x)
    x = _SIG_HEX.sub('<HEX>', x)
    x = _SIG_NUM.sub('<NUM>', x)
    x = _SIG_SQ.sub("'<STR>'", x)
    x = _SIG_DQ.sub('"<STR>"', x)
    # You can also collapse whitespace if desired.
    digest = hashlib.sha1(x.encode('utf-8')).hexdigest()
    return digest

def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS triage_cache (
            sig TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    return con

def get(sig: str):
    con = _conn()
    try:
        row = con.execute("SELECT payload FROM triage_cache WHERE sig=?", (sig,)).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        con.close()

def put(sig: str, payload: dict, now_ts: int):
    con = _conn()
    try:
        blob = json.dumps(payload, ensure_ascii=False)
        con.execute(
            "INSERT INTO triage_cache(sig,payload,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(sig) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (sig, blob, now_ts),
        )
        con.commit()
    finally:
        con.close()
