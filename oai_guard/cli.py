#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os
from typing import List, Tuple
from .model import Config
from .triage import handle_error

def read_last_error_with_context(path: str, window: int = 30) -> Tuple[str, List[str]]:
    with open(path, "r", errors="ignore") as f:
        lines = f.readlines()
    idx = None
    for i in range(len(lines) - 1, -1, -1):
        if "ERROR" in lines[i]:
            idx = i; break
    if idx is None:
        raise SystemExit("No ERROR line found in the log.")
    start = max(0, idx - (window - 1))
    return lines[idx].rstrip("\n"), [l.rstrip("\n") for l in lines[start:idx+1]]

def main():
    ap = argparse.ArgumentParser("oai-guard (OpenAI-powered)")
    ap.add_argument("logfile", help="Path to log file")
    ap.add_argument("--window", type=int, default=30, help="Context lines to include (tail)")
    ap.add_argument("--last", action="store_true", help="Analyze only the last ERROR line")
    ap.add_argument("--auto", action="store_true", help="Attempt safe auto-resolution (policy constrained)")
    ap.add_argument("--no-heur", dest="no_heur", action="store_true", help="Disable heuristic fast-path (force model JSON)")
    ap.add_argument("--engine", default=os.environ.get("OAI_ENGINE", "openai"),
                    choices=["openai","ollama"], help="Inference engine")
    # OpenAI params
    ap.add_argument("--openai-model", default=os.environ.get("OPENAI_MODEL", "gpt-4o"))
    ap.add_argument("--openai-max-tokens", type=int, default=int(os.environ.get("OPENAI_MAX_TOKENS", "256")))
    ap.add_argument("--openai-temperature", type=float, default=float(os.environ.get("OPENAI_TEMPERATURE", "0")))
    ap.add_argument("--openai-timeout", type=int, default=int(os.environ.get("OPENAI_TIMEOUT", "60")))
    # Ollama params (kept for compatibility)
    ap.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--ollama-model", default=os.environ.get("OLLAMA_MODEL", "llama3.2:1b"))
    ap.add_argument("--ollama-timeout", type=int, default=int(os.environ.get("OLLAMA_TIMEOUT", "60")))
    ap.add_argument("--ollama-opts", default=os.environ.get("OLLAMA_OPTS",
                        '{"temperature":0,"num_predict":128,"num_ctx":256,"num_thread":4,"keep_alive":-1}'))
    args = ap.parse_args()

    cfg = Config(
        engine=args.engine,
        openai_model=args.openai_model,
        openai_timeout=args.openai_timeout,
        openai_max_tokens=args.openai_max_tokens,
        openai_temperature=args.openai_temperature,
        ollama_url=args.ollama_url,
        ollama_model=args.ollama_model,
        ollama_timeout=args.ollama_timeout,
        ollama_opts_json=args.ollama_opts,
    )

    err, ctx = read_last_error_with_context(args.logfile, args.window)
    heur_state = 'OFF' if args.no_heur else 'ON'
    print(f"[oai-guard] engine={cfg.engine} model={cfg.openai_model if cfg.engine=='openai' else cfg.ollama_model} heuristics={heur_state}")
    if args.last:
        print("[+] Last error:"); print(err)
        print(f"[+] Context lines: {len(ctx)}")
    handle_error(err, ctx, cfg, auto=args.auto, use_heuristics=not args.no_heur)

if __name__ == "__main__":
    main()
