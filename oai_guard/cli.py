import argparse, sys
from collections import deque

from .config import Config
from .sources import (
    follow_file, scan_file_once, last_error_event,
    load_events_from_json, last_error_event_from_json, lines_from_events
)
from .parsing import LEVEL_RE, parse_line_to_kv, is_error_level
from .triage import handle_error

def _p(msg: str):
    print(msg, flush=True)

def main():
    cfg = Config()

    ap = argparse.ArgumentParser(description="OpenAir log guard (Ollama-powered, structured).")
    ap.add_argument("log_path", nargs="?", default="/var/log/openair.log",
                    help="Path to the log file (ignored if --json-file is used).")
    ap.add_argument("--auto", action="store_true",
                    help="Auto-run approved fixes when risk=low & no human review needed.")
    ap.add_argument("--once", action="store_true",
                    help="Scan whole file once (collect all errors) then exit.")
    ap.add_argument("--workers", type=int, default=1,
                    help="(reserved) concurrency for --once.")
    ap.add_argument("--last", action="store_true",
                    help="Process only the most recent error in the last WINDOW lines, then exit.")
    ap.add_argument("--window", type=int, default=None,
                    help="Lines to scan for --last; defaults to WINDOW env.")
    ap.add_argument("--json-file",
                    help="Read KV events from JSON (object or array), instead of a log file.")

    # Demo speed / behavior toggles
    ap.add_argument("--fast", dest="fast", action="store_true",
                    help="Use heuristic triage first (skip LLM if matched).")
    ap.add_argument("--no-fast", dest="fast", action="store_false",
                    help="Disable heuristic fast path.")
    ap.set_defaults(fast=None)
    ap.add_argument("--fast-only", action="store_true",
                    help="If heuristic matches, DO NOT call LLM.")
    ap.add_argument("--no-diagnostics", dest="no_diag", action="store_true",
                    help="Skip diagnostics for speed.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Print extra progress info.")

    # LLM after heuristic (optional)
    ap.add_argument("--llm-verify", action="store_true",
                    help="If heuristic matches, also call LLM and REPLACE with LLM result.")
    ap.add_argument("--llm-augment", action="store_true",
                    help="If heuristic matches, also call LLM and MERGE extra details in.")

    # History cache toggle & proof
    ap.add_argument("--no-history", action="store_true",
                    help="Do not reuse previous triage from history cache.")
    ap.add_argument("--prove-json", action="store_true",
                    help="Embed structured JSON and prompt preview into the incident file.")

    # Auto-restart policy
    ap.add_argument("--auto-policy", choices=["oai_only", "whitelist", "any"],
                    help="Policy for auto restarts. Default comes from AUTO_POLICY env.")
    ap.add_argument("--whitelist-file",
                    help="Path to whitelist file for --auto-policy=whitelist.")

    args = ap.parse_args()

    # Decide verify/augment mode
    llm_mode = "verify" if args.llm_verify else ("augment" if args.llm_augment else "off")

    # Apply toggles into config (dataclass is frozen; create a new one when overriding)
    if args.no_diag:
        cfg = Config(**{**cfg.__dict__, "skip_diagnostics": True})

    if args.auto_policy or args.whitelist_file:
        cfg = Config(**{
            **cfg.__dict__,
            "auto_policy": args.auto_policy or cfg.auto_policy,
            "whitelist_file": args.whitelist_file or cfg.whitelist_file,
        })

    prefer_fast = args.fast  # None → Config.fast_first
    window = args.window if args.window is not None else cfg.window

    # Banner
    _p(
        f"[oai-guard] start | model={cfg.model} | last={args.last} once={args.once} "
        f"fast={args.fast} fast_only={args.fast_only} no_diag={args.no_diag} "
        f"llm_mode={llm_mode} history={'off' if args.no_history else 'on'} "
        f"auto_policy={cfg.auto_policy} window={window}"
    )

    def triage(line: str, ctx: list[str]):
        if args.verbose:
            _p(f"[oai-guard] triaging ({len(ctx)} ctx lines)…")
        out = handle_error(
            line, ctx, cfg,
            auto=args.auto,
            prefer_fast=prefer_fast,
            fast_only=args.fast_only,
            verbose=args.verbose,
            llm_mode=llm_mode,
            reuse_history=not args.no_history,
            prove_json=args.prove_json,
        )
        _p(f"[+] Incident saved: {out}")

    # JSON input mode
    if args.json_file:
        events = load_events_from_json(args.json_file)
        if args.last:
            evt = last_error_event_from_json(events, cfg.context_lines)
            if not evt:
                _p("No error-level events found in JSON.")
                return
            err, ctx = evt
            _p(f"[+] Last error (JSON):\n{err}\n[+] Context lines: {len(ctx)}")
            triage(err, ctx)
            return

        lines = lines_from_events(events)
        buf = deque(maxlen=cfg.context_lines); count = 0
        for line in lines:
            buf.append(line)
            kv = parse_line_to_kv(line)
            if LEVEL_RE.search(line) or is_error_level(kv.get("level", "")):
                count += 1
                triage(line, list(buf))
        _p(f"[+] Processed {count} error events from JSON.")
        return

    # Log file modes
    if args.last:
        evt = last_error_event(args.log_path, window, cfg.context_lines)
        if not evt:
            _p(f"No error-like lines found in the last {window} lines.")
            return
        err, ctx = evt
        _p(f"[+] Last error:\n{err}\n[+] Context lines: {len(ctx)}")
        triage(err, ctx)
        return

    if args.once:
        events = scan_file_once(args.log_path, cfg.context_lines)
        _p(f"[+] Found {len(events)} error events")
        for line, ctx in events:
            triage(line, ctx)
        return

    # Live mode
    _p(f"[+] Monitoring {args.log_path} | model={cfg.model} | auto={args.auto}")
    buf = deque(maxlen=cfg.context_lines)
    for line in follow_file(args.log_path, cfg.tail_n):
        buf.append(line)
        if LEVEL_RE.search(line):
            try:
                triage(line, list(buf))
            except Exception as e:
                _p(f"[x] Handler failed: {e}")

if __name__ == "__main__":
    main()

