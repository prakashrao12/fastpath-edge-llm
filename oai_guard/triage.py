import os, re, json, sys, time
from typing import List, Dict, Optional

from .config import Config
from .parsing import kvs_from_lines
from .model import post_chat, extract_json, _gen_prompt  # _gen_prompt used for prompt preview
from .actions import (
    ensure_dirs, allowed, run_cmd, ts,
    approve_fix_cmd, auto_execute_fix,  # auto-restart policy helpers
)



# ---- optional history cache (silently disabled if module/file not present) ----
HISTORY_AVAILABLE = False
try:
    from .history import make_signature, get as hist_get, put as hist_put  # type: ignore
    HISTORY_AVAILABLE = True
except Exception:
    def make_signature(line: str) -> str: return ""
    def hist_get(sig: str): return None
    def hist_put(sig: str, payload: dict, now_ts: int): return None

def _log(msg: str, verbose: bool = False):
    if verbose:
        print(msg, file=sys.stderr, flush=True)

# dynamic demo: [DEMO] ERROR service <name> down
_DYN_DEMO = re.compile(r"\[DEMO\]\s+ERROR\s+service\s+([A-Za-z0-9@_.\-]+)\s+down", re.I)

# ---- Heuristic (regex) rules for instant triage (FAST PATH) ----

# Each entry: (compiled_regex, recipe_dict)

_HEUR: List[tuple[re.Pattern, Dict]] = [
    (
        re.compile(r"DNN\s+'([^']+)'\s+not configured", re.I),
        {
            "summary": "Requested DNN is not configured in SMF",
            "causes": [
                "UE requested an unknown DNN",
                "SMF configuration missing the requested DNN/APN",
            ],
            "diag": [
                "journalctl -u oai-smf -n 200",
                "grep -n \"DNN\" /etc/oai/smf.conf",
            ],
            "fix": [
                "systemctl status oai-smf",
                "systemctl restart oai-smf",
            ],
            "risk": "medium",
            "need_hr": True,
        },
    ),
    (
        re.compile(r"PFCP.*Association.*timed out", re.I),
        {
            "summary": "SMF↔UPF PFCP association timed out",
            "causes": [
                "UPF service is down or unreachable",
                "Firewall/port blocking (UDP 8805)",
                "Incorrect UPF IP/port in SMF config",
            ],
            "diag": [
                "systemctl status oai-upf",
                "journalctl -u oai-upf -n 200",
            ],
            "fix": [
                "systemctl restart oai-upf",
            ],
            "risk": "low",
            "need_hr": False,
        },
    ),
    (
        re.compile(r"GTP-U.*Address already in use", re.I),
        {
            "summary": "UPF cannot bind GTP-U (port already in use)",
            "causes": [
                "Another GTP-U process bound to UDP/2152",
                "Stale/zombie UPF instance",
            ],
            "diag": [
                "systemctl status oai-upf",
                "journalctl -u oai-upf -n 200",
            ],
            "fix": [
                "systemctl restart oai-upf",
            ],
            "risk": "low",
            "need_hr": False,
        },
    ),
    (
        re.compile(r"NRF registration failed.*\b503\b", re.I),
        {
            "summary": "AMF NRF registration failed (HTTP 503)",
            "causes": [
                "NRF not healthy or still starting",
                "Network issue between AMF and NRF",
            ],
            "diag": [
                "systemctl status oai-nrf",
                "journalctl -u oai-nrf -n 200",
                "journalctl -u oai-amf -n 200",
            ],
            "fix": [
                "systemctl restart oai-nrf",
            ],
            "risk": "low",
            "need_hr": False,
        },
    ),
    (
        re.compile(r"\bT3560\b.*expired", re.I),
        {
            "summary": "UE authentication timed out (T3560)",
            "causes": [
                "UE unreachable / radio issue",
                "gNB↔AMF signaling problem",
            ],
            "diag": [
                "journalctl -u oai-amf -n 200",
            ],
            "fix": [],
            "risk": "medium",
            "need_hr": True,
        },
    ),
]

def _heuristic_triage(error_line: str) -> Optional[Dict]:
    # dynamic demo rule first
    m = _DYN_DEMO.search(error_line)
    if m:
        svc = m.group(1)
        return {
            "incident_summary": f"Service {svc} is reported down",
            "probable_causes": [
                "Service crashed or was stopped",
                "Temporary resource/network condition"
            ],
            "diagnostics_cmds": [f"systemctl status {svc}", f"journalctl -u {svc} -n 200"],
            "fix_cmds": [f"systemctl restart {svc}"],
            "risk_level": "low",
            "need_human_review": False,
        }
    # existing static patterns below...
    for pat, rec in _HEUR:
        if pat.search(error_line):
            return {
                "incident_summary": rec["summary"],
                "probable_causes": rec["causes"],
                "diagnostics_cmds": rec["diag"],
                "fix_cmds": rec["fix"],
                "risk_level": rec["risk"],
                "need_human_review": rec["need_hr"],
            }
    return None

def system_prompt(cfg: Config) -> str:
    return (
        "You are a senior SRE for OpenAirInterface (OAI) core (AMF/SMF/UPF/NRF/NGAP/NAS/RRC/PFCP).\n"
        f"Given (1) recent log text, (2) structured JSON context, and (3) the error line, "
        "return STRICT JSON ONLY with keys:\n"
        "- incident_summary (string)\n"
        "- probable_causes (array of strings)\n"
        f"- diagnostics_cmds (array of safe commands; prefixes allowed: {cfg.allowlist})\n"
        f"- fix_cmds (array of minimal safe commands; prefixes allowed only)\n"
        '- risk_level (\"low\"|\"medium\"|\"high\")\n'
        "- need_human_review (boolean)\n"
        "Rules: JSON only. Prefer reversible fixes. If unsure, set need_human_review=true.\n"
    )

def handle_error(
    error_line: str,
    ctx_lines: List[str],
    cfg: Config,
    auto: bool = False,
    prefer_fast: Optional[bool] = None,
    fast_only: bool = False,
    verbose: bool = False,
    llm_mode: str = "off",      # "off" | "verify" | "augment"
    reuse_history: bool = True,
    prove_json: bool = False,   # embed structured_context + prompt preview into incident
) -> str:
    """
    Returns path to the saved incident JSON.

    Decision order:
      0) history (if enabled and hit)
      1) heuristics (if enabled and match)
      2) LLM (unless fast_only)
      2b) If heuristics matched and llm_mode is verify/augment, also call LLM.
    """
    source = "unknown"
    use_fast = cfg.fast_first if prefer_fast is None else prefer_fast

    # 0) HISTORY
    data: Optional[Dict] = None
    sig = ""
    if reuse_history and HISTORY_AVAILABLE:
        sig = make_signature(error_line)
        cached = hist_get(sig)
        if cached:
            _log("[history] hit → reusing previous triage", verbose)
            data = cached
            source = "history"

    # 1) HEURISTICS
    if data is None and use_fast:
        data = _heuristic_triage(error_line)
        if data:
            _log("[fast] heuristic matched.", verbose)
            source = "heuristic"

    # Prepare LLM messages / context (used in several branches)
    structured_ctx = kvs_from_lines(ctx_lines)
    context_text   = "\n".join(ctx_lines)
    structured_blk = json.dumps({"recent_context": structured_ctx}, ensure_ascii=False)
    base_msgs = [
        {"role": "system", "content": system_prompt(cfg)},
        {"role": "user", "content":
            "Recent log context (latest at end):\n```\n" + context_text + "\n```\n\n" +
            "Structured context (JSON):\n```json\n" + structured_blk + "\n```\n\n" +
            "Error line (raw):\n```\n" + error_line + "\n```"
        }
    ]

    # Optional proof payloads (for auditing)
    prompt_preview = _gen_prompt(base_msgs)[:1200] if prove_json else None

    def call_llm() -> Dict:
        _log("[llm] calling model…", verbose)
        raw = post_chat(base_msgs, cfg)
        try:
            d = extract_json(raw)
        except Exception:
            _log("[llm] invalid JSON, retrying…", verbose)
            d = extract_json(post_chat(base_msgs + [
                {"role": "user", "content": "Previous reply was invalid JSON. Send one complete STRICT JSON object only."}
            ], cfg))
        _log("[llm] got structured JSON.", verbose)
        return d

    # 2) LLM fallback if nothing else produced data (unless fast_only)
    if data is None and not fast_only:
        data = call_llm()
        source = "llm"

    # If heuristics produced data and user asked to verify/augment, also call LLM
    if data is not None and source == "heuristic" and not fast_only and llm_mode in ("verify", "augment"):
        llm_data = call_llm()
        if llm_mode == "verify":
            data = llm_data
            source = "llm"
        else:
            # augment: merge lists uniquely; prefer LLM summary/risk/review flags if present
            data["incident_summary"] = llm_data.get("incident_summary") or data.get("incident_summary")
            for key in ("probable_causes", "diagnostics_cmds", "fix_cmds"):
                merged = list(dict.fromkeys([*data.get(key, []), *llm_data.get(key, [])]))
                data[key] = merged
            if llm_data.get("risk_level"):
                data["risk_level"] = llm_data["risk_level"]
            if "need_human_review" in llm_data:
                data["need_human_review"] = llm_data["need_human_review"]
            source = "heuristic+llm"

    # If still no data (fast_only with no match), synthesize a minimal record
    if data is None:
        data = {
            "incident_summary": "No triage available (fast-only with no heuristic match).",
            "probable_causes": [],
            "diagnostics_cmds": [],
            "fix_cmds": [],
            "risk_level": "",
            "need_human_review": True,
        }
        source = "none"

    # 3) Save to history (if enabled & not already a pure history hit)
    if reuse_history and HISTORY_AVAILABLE and source != "history":
        if not sig:
            sig = make_signature(error_line)
        hist_put(sig, data, now_ts=int(time.time()))

    # 4) Build incident record
    record: Dict = {
        "timestamp": ts(),
        "source": source,                 # where the answer came from
        "error_line": error_line,
        "summary": data.get("incident_summary"),
        "causes": data.get("probable_causes", []),
        "diagnostics_cmds": [c for c in data.get("diagnostics_cmds", []) if allowed(c, cfg)],
        "fix_cmds": [c for c in data.get("fix_cmds", []) if allowed(c, cfg)],
        "risk_level": str(data.get("risk_level", "")).lower(),
        "need_human_review": bool(data.get("need_human_review", True)),
        "auto_ran": False,
        "results": [],
    }
    if prove_json:
        record["structured_context"] = structured_ctx
        record["prompt_preview"] = prompt_preview

    # 5) Diagnostics (optional for speed)
    if record["diagnostics_cmds"] and not getattr(cfg, "skip_diagnostics", False):
        for cmd in record["diagnostics_cmds"]:
            _log(f"[diag] {cmd}", verbose)
            record["results"].append(run_cmd(cmd))

    # 6) Optional fixes (AUTO) - only when model/heuristics say low risk & no human review
    if auto and not record["need_human_review"] and record["risk_level"] == "low":
        did_any = False
        for cmd in record["fix_cmds"]:
            if not allowed(cmd, cfg):
                record["results"].append({"cmd": cmd, "rc": -2, "stdout": "", "stderr": "blocked by allowlist"})
                continue
            if approve_fix_cmd(cmd, cfg):
                _log(f"[auto-fix] {cmd}", verbose)
                record["results"].append(auto_execute_fix(cmd, cfg))
                did_any = True
            else:
                record["results"].append({"cmd": cmd, "rc": -2, "stdout": "", "stderr": "auto policy rejected"})
        record["auto_ran"] = did_any

    # 7) Persist
    ensure_dirs(cfg.incident_dir)
    out_path = os.path.join(cfg.incident_dir, f"incident_{record['timestamp']}.json")
    with open(out_path, "w") as f:
        json.dump(record, f, indent=2)
    return out_path

