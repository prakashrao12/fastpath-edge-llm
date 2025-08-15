import os, re, shlex, subprocess, time
from .config import Config

# --- generic helpers already used elsewhere ---
def ensure_dirs(path: str):
    os.makedirs(path, exist_ok=True)

def ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")

def run_cmd(cmd: str) -> dict:
    try:
        parts = shlex.split(cmd)
        p = subprocess.run(parts, capture_output=True, text=True, timeout=180)
        return {"cmd": cmd, "rc": p.returncode, "stdout": p.stdout[-4000:], "stderr": p.stderr[-4000:]}
    except Exception as e:
        return {"cmd": cmd, "rc": -1, "stdout": "", "stderr": str(e)}

def allowed(cmd: str, cfg: Config) -> bool:
    cmd = cmd.strip()
    return any(cmd.startswith(p) for p in cfg.allowlist)

# --- AUTO RESTART LOGIC ---

# Only accept very conservative "systemctl restart <svc>[.service]" commands.
# Service token must be a simple unit name (no spaces, pipes, semicolons, etc.)
_SYSTEMCTL_RE = re.compile(
    r"^systemctl\s+(?:--now\s+)?(restart|start|stop)\s+([A-Za-z0-9@_.\-]+)(?:\.service)?\s*$"
)

def parse_systemctl(cmd: str):
    m = _SYSTEMCTL_RE.match(cmd.strip())
    if not m:
        return None
    action, service = m.group(1), m.group(2)
    return action, service

def _load_whitelist(path: str) -> set[str]:
    try:
        with open(path, "r") as f:
            return {
                ln.strip() for ln in f
                if ln.strip() and not ln.strip().startswith("#")
            }
    except Exception:
        return set()

def approve_fix_cmd(cmd: str, cfg: Config) -> bool:
    """
    Decide if a fix command is allowed for AUTO execution.
    Policy:
      - Only 'systemctl restart <service>' is auto-runnable.
      - Policy 'oai_only': service must start with 'oai-'
      - Policy 'whitelist': service must be present in whitelist file
      - Policy 'any': any service token matching the regex is allowed (riskier)
    """
    parsed = parse_systemctl(cmd)
    if not parsed:
        return False
    action, service = parsed
    if action != "restart":
        return False

    policy = cfg.auto_policy
    if policy == "oai_only":
        return service.startswith("oai-")
    if policy == "whitelist":
        wl = _load_whitelist(cfg.whitelist_file)
        return service in wl
    if policy == "any":
        return True
    return False

def restart_service_and_verify(service: str, cfg: Config) -> dict:
    """
    Restart the service and verify it becomes 'active' within a timeout window.
    """
    res_restart = run_cmd(f"systemctl restart {service}")
    # Even if restart rc != 0, try to verify current state to give more info.
    deadline = time.time() + cfg.auto_verify_timeout
    interval = max(1, cfg.auto_verify_interval)
    last_state = {"stdout": "", "stderr": "", "rc": 1}

    while time.time() < deadline:
        p = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True)
        last_state = {"stdout": (p.stdout or "").strip(), "stderr": (p.stderr or "").strip(), "rc": p.returncode}
        if p.returncode == 0 and last_state["stdout"] == "active":
            break
        time.sleep(interval)

    out = {
        "cmd": f"systemctl restart {service}",
        "rc": res_restart["rc"],
        "stdout": res_restart["stdout"],
        "stderr": res_restart["stderr"],
        "verify_state": last_state["stdout"] or "unknown",
        "verify_rc": last_state["rc"],
    }
    return out

def auto_execute_fix(cmd: str, cfg: Config) -> dict:
    """
    Execute an approved fix command with extra semantics for systemctl restart.
    If the command is not an approved systemctl restart, refuse with rc=-2.
    """
    parsed = parse_systemctl(cmd)
    if parsed and parsed[0] == "restart" and approve_fix_cmd(cmd, cfg):
        return restart_service_and_verify(parsed[1], cfg)
    return {"cmd": cmd, "rc": -2, "stdout": "", "stderr": "auto policy rejected or unsupported fix type"}
