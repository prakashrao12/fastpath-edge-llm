#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, json, subprocess, time
from typing import List, Dict, Any, Optional, Tuple
from .model import Config, post_chat

INCIDENT_DIR = os.environ.get("OAI_INCIDENT_DIR", "/var/log/oai_incidents")
os.makedirs(INCIDENT_DIR, exist_ok=True)

USE_HEUR_DEFAULT = os.environ.get("OAI_USE_HEUR", "1") != "0"

_JSON_SYSPROMPT = (
    "You are a telecom (4G/5G core) troubleshooting assistant. "
    "Return ONLY a single JSON object with keys:\n"
    '  "summary": short string (<= 20 words),\n'
    '  "causes": array of 1-3 short strings,\n'
    '  "diagnostics_cmds": array of up to 5 safe READ-ONLY shell commands,\n'
    '  "fix_cmds": array of up to 3 safe commands (prefer systemctl restart),\n'
    '  "risk_level": "low" | "medium" | "high",\n'
    '  "need_human_review": true|false.\n'
    "NO prose, NO markdown, ONLY JSON."
)

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None

# ---------------- Heuristics (optional fast path) ----------------
_HEUR = [
    (re.compile(r"DNN .*not configured", re.I),
     lambda line: {
         "summary": "Requested DNN not configured in SMF",
         "causes": ["UE requested unknown DNN/APN", "SMF config missing DNN"],
         "diagnostics_cmds": [
             "journalctl -u oai-smf -n 120",
             "grep -n \"DNN\" /etc/oai/smf.conf"
         ],
         "fix_cmds": ["systemctl restart oai-smf"],
         "risk_level": "medium",
         "need_human_review": True,
     }),
    (re.compile(r"NRF registration failed.*503", re.I),
     lambda line: {
         "summary": "NRF unavailable (503) during registration",
         "causes": ["NRF down", "Network partition"],
         "diagnostics_cmds": [
             "systemctl status oai-nrf",
             "journalctl -u oai-nrf -n 200"
         ],
         "fix_cmds": ["systemctl restart oai-nrf"],
         "risk_level": "medium",
         "need_human_review": True,
     }),
    (re.compile(r"PFCP.*Association.*timed out", re.I),
     lambda line: {
         "summary": "PFCP association timeout to UPF",
         "causes": ["UPF not reachable", "Firewall/port 8805 blocked"],
         "diagnostics_cmds": [
             "journalctl -u oai-upf -n 120",
             "ss -lntup | grep 8805"
         ],
         "fix_cmds": ["systemctl restart oai-upf"],
         "risk_level": "medium",
         "need_human_review": True,
     }),
    (re.compile(r"T3560 expired", re.I),
     lambda line: {
         "summary": "UE auth timeout (T3560)",
         "causes": ["HSS/AUSF delay", "UE unreachable"],
         "diagnostics_cmds": [
             "journalctl -u oai-ausf -n 120",
             "journalctl -u oai-amf -n 120"
         ],
         "fix_cmds": ["systemctl restart oai-amf"],
         "risk_level": "low",
         "need_human_review": True,
     }),
]

# ---------------- Safe exec policy ----------------
_SAFE_SVC = re.compile(
    r"^(oai|open5gs)-(amf|smf|upf|ausf|nrf|pcf|udm|udr|bsf)d?$|^demo-svc$",
    re.I
)

def _run_safe(cmd: str, timeout: int = 20) -> Dict[str, Any]:
    cmd = cmd.strip()
    # now allow: status | restart | start
    m = re.match(r"^systemctl\s+(status|restart|start)\s+([a-zA-Z0-9\-_.]+)$", cmd)
    if not m or not _SAFE_SVC.match(m.group(2)):
        return {"cmd": cmd, "skipped": True, "reason": "blocked by policy"}
    try:
        out = subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT, timeout=timeout).decode("utf-8", "ignore")
        return {"cmd": cmd, "skipped": False, "rc": 0, "out": out[:4000]}
    except subprocess.CalledProcessError as e:
        return {"cmd": cmd, "skipped": False, "rc": e.returncode, "out": (e.output or b'').decode('utf-8','ignore')[:4000]}
    except Exception as e:
        return {"cmd": cmd, "skipped": False, "rc": -1, "out": str(e)}


# ---------------- Baseline fallback (no model JSON) ----------------
_COMP2SVC = {
    "SMF": ["oai-smf", "open5gs-smfd"],
    "AMF": ["oai-amf", "open5gs-amfd"],
    "UPF": ["oai-upf", "open5gs-upfd"],
    "NRF": ["oai-nrf", "open5gs-nrfd"],
    "AUSF": ["oai-ausf", "open5gs-ausfd"],
    "PCF": ["oai-pcf", "open5gs-pcfd"],
    "UDM": ["oai-udm", "open5gs-udmd"],
    "UDR": ["oai-udr", "open5gs-udrd"],
    "BSF": ["oai-bsf", "open5gs-bsfd"],
    "DEMO": ["demo-svc"],
}

def _guess_component(error_line: str) -> str:
    m = re.search(r"\[([A-Z]{2,4})\]", error_line)
    return (m.group(1) if m else "").upper()

def _baseline_plan(error_line: str) -> Dict[str, Any]:
    comp = _guess_component(error_line)
    services = _COMP2SVC.get(comp, [])
    # choose first service for restart; list both in diagnostics
    primary = services[0] if services else "oai-smf"
    diags = []
    for svc in services or [primary]:
        diags.append(f"systemctl status {svc}")
        diags.append(f"journalctl -u {svc} -n 200")
    # add one generic readonly check
    diags.append("ss -lntup | head -n 30")

    return {
        "summary": f"{comp or 'Core'} issue detected; baseline triage",
        "causes": ["Model returned no JSON; generic plan applied"],
        "diagnostics_cmds": diags[:5],
        "fix_cmds": [f"systemctl restart {primary}"],
        "risk_level": "low",
        "need_human_review": True,
    }

def _heuristic_triage(error_line: str) -> Optional[Dict[str, Any]]:
    for pat, rec in _HEUR:
        if pat.search(error_line):
            return rec(error_line)
    return None

def handle_error(error_line: str, ctx_lines: List[str], cfg: Config, auto: bool = False, use_heuristics: bool = USE_HEUR_DEFAULT) -> Dict[str, Any]:
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    incident = {
        "timestamp": ts,
        "engine": cfg.engine,
        "model": cfg.openai_model if cfg.engine == "openai" else cfg.ollama_model,
        "error_line": error_line,
        "context_tail": ctx_lines[-32:],
        "summary": "",
        "causes": [],
        "diagnostics_cmds": [],
        "fix_cmds": [],
        "risk_level": "low",
        "need_human_review": True,
        "auto_ran": False,
        "results": [],
        "model_raw": "",
        "retry_raw": "",
    }

    heur = _heuristic_triage(error_line) if use_heuristics else None
    used_baseline = False

    if heur:
        incident.update(heur)
    else:
        # 1st: model JSON
        ctx = "\n".join(ctx_lines[-32:])
        sys = _JSON_SYSPROMPT
        usr = f"ERROR:\n{error_line}\n\nCONTEXT (tail):\n{ctx}\n\nReturn ONLY JSON."
        raw = post_chat(
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            cfg=cfg,
        )
        incident["model_raw"] = raw or ""
        data = extract_json(raw or "")

        # 2nd: strict retry if needed
        if not data:
            usr2 = (
                "STRICT_JSON_ONLY. Keys: summary, causes[], diagnostics_cmds[], fix_cmds[], "
                "risk_level(low|medium|high), need_human_review(boolean). "
                f"ERROR: {error_line}. Do not include markdown or prose."
            )
            raw2 = post_chat(messages=[{"role": "system", "content": sys}, {"role": "user", "content": usr2}], cfg=cfg)
            incident["retry_raw"] = raw2 or ""
            data = extract_json(raw2 or "")

        # 3rd: baseline fallback (always produce something)
        if data:
            for k in ("summary", "causes", "diagnostics_cmds", "fix_cmds", "risk_level", "need_human_review"):
                if k in data:
                    incident[k] = data[k]
        else:
            incident.update(_baseline_plan(error_line))
            used_baseline = True

    if auto and incident.get("fix_cmds"):
        results = []
        for cmd in incident["fix_cmds"]:
            results.append(_run_safe(cmd))
        incident["results"] = results
        incident["auto_ran"] = True

    path = os.path.join(INCIDENT_DIR, f"incident_{ts}.json")
    with open(path, "w") as f:
        json.dump(incident, f, indent=2)
    print(f"[+] Incident saved: {path}" + (" (baseline)" if used_baseline else ""))
    return incident
