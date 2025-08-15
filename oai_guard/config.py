from dataclasses import dataclass, field
import os

def _split_allowlist(s: str):
    return [p.strip() for p in s.split(",") if p.strip()]

@dataclass(frozen=True)
class Config:
    model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2"))
    base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"))
    incident_dir: str = field(default_factory=lambda: os.getenv("INCIDENT_DIR", "/var/log/oai_incidents"))
    context_lines: int = field(default_factory=lambda: int(os.getenv("CONTEXT_LINES", "50")))
    tail_n: int = field(default_factory=lambda: int(os.getenv("TAIL_N", "0")))
    timeout_sec: int = field(default_factory=lambda: int(os.getenv("OLLAMA_TIMEOUT", "120")))
    window: int = field(default_factory=lambda: int(os.getenv("WINDOW", "800")))
    allowlist: list[str] = field(default_factory=lambda: _split_allowlist(
        os.getenv("ALLOWLIST", "systemctl status,systemctl restart,journalctl -u,grep,tail")
    ))
    keep_alive: str = field(default_factory=lambda: os.getenv("KEEP_ALIVE", "-1"))
    fast_first: bool = field(default_factory=lambda: os.getenv("FAST_FIRST", "1").lower() not in ("0","false","no"))
    skip_diagnostics: bool = field(default_factory=lambda: os.getenv("SKIP_DIAG", "0").lower() in ("1","true","yes"))

    # --- NEW: auto-restart policy knobs ---
    auto_policy: str = field(default_factory=lambda: os.getenv("AUTO_POLICY", "oai_only"))  # 'oai_only'|'whitelist'|'any'
    whitelist_file: str = field(default_factory=lambda: os.getenv("WHITELIST_FILE", "/etc/oai-guard-whitelist.txt"))
    auto_verify_timeout: int = field(default_factory=lambda: int(os.getenv("AUTO_VERIFY_TIMEOUT", "20")))
    auto_verify_interval: int = field(default_factory=lambda: int(os.getenv("AUTO_VERIFY_INTERVAL", "2")))
