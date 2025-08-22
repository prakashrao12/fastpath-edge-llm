#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Latency & TTFB comparator: local Ollama vs OpenAI Chat Completions
#
# Quick start:
#   pip3 install requests
#   export OLLAMA_MODEL=phi3:mini
#   export OLLAMA_OPTS='{"temperature":0,"top_k":1,"top_p":0,"num_predict":8,"num_ctx":96,"num_thread":16,"keep_alive":-1}'
#   export OPENAI_MODEL=gpt-4o
#   export OPENAI_API_KEY=sk-...
#
#   python3 diag_compare.py \
#     --log /var/log/openair.log --window 0 \
#     --prompt-template speed_prompt.json.txt \
#     --ollama-model "$OLLAMA_MODEL" --ollama-opts "$OLLAMA_OPTS" \
#     --openai-model "$OPENAI_MODEL" --openai-max-tokens 64 \
#     --ttfb --runs 5 --timeout 30

import argparse
import os
import sys
import time
import json
import math
import csv
from typing import Optional, Tuple, List

try:
    import requests
except Exception:
    print("This script requires 'requests' (pip install requests)", file=sys.stderr)
    raise


# ---------- Log parsing & prompt rendering ----------

def read_last_error_line(log_path: str) -> Tuple[str, int, List[str]]:
    with open(log_path, 'r', errors='ignore') as f:
        lines = f.read().splitlines()
    idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if "ERROR" in lines[i]:
            idx = i
            break
    if idx == -1:
        raise RuntimeError("No line containing 'ERROR' found in log.")
    return lines[idx], idx, lines


def window_context(lines: List[str], idx: int, window: int) -> List[str]:
    if window <= 0:
        return []
    start = max(0, idx - window)
    end = min(len(lines), idx + window + 1)
    return lines[start:end]


def render_prompt(template_path: Optional[str], error_line: str, ctx_lines: List[str]) -> str:
    if template_path and os.path.exists(template_path):
        with open(template_path, 'r', encoding='utf-8') as f:
            tpl = f.read()
    else:
        # Fallback template
        tpl = (
            "Return ONLY JSON with keys exactly:\n"
            "- summary (<=20 words)\n"
            "- steps (array of <=5 short shell commands; read-only where possible)\n"
            "- risk (\"low\"|\"medium\"|\"high\")\n\n"
            "ERROR:\n{error_line}\n"
        )
        if ctx_lines:
            tpl += "\nCONTEXT:\n{context}\n"
    filled = tpl.replace("{error_line}", error_line)
    if "{context}" in filled:
        filled = filled.replace("{context}", "\n".join(ctx_lines))
    return filled


# ---------- Engines ----------

def call_ollama(
    url: str,
    model: str,
    prompt: str,
    opts,
    timeout: int,
    measure_ttfb: bool = False
):
    """
    Calls Ollama /api/generate. Forces format=json for cleaner output.
    Returns: (text, total_sec, ttfb_sec_or_None)
    """
    try:
        o = json.loads(opts) if isinstance(opts, str) else dict(opts or {})
    except Exception:
        o = {}

    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "options": o,
        "stream": bool(measure_ttfb),
    }
    if "keep_alive" in o:
        payload["keep_alive"] = o["keep_alive"]

    start = time.perf_counter()
    if measure_ttfb:
        ttfb = None
        acc = []
        with requests.post(f"{url.rstrip('/')}/api/generate", json=payload, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if ttfb is None:
                    ttfb = (time.perf_counter() - start)
                try:
                    obj = json.loads(line)
                    piece = obj.get("response", "")
                except Exception:
                    piece = line
                if piece:
                    acc.append(piece)
        total = (time.perf_counter() - start)
        return "".join(acc).strip(), total, ttfb
    else:
        r = requests.post(f"{url.rstrip('/')}/api/generate", json=payload, timeout=timeout)
        r.raise_for_status()
        obj = r.json()
        text = (obj.get("response") or "").strip()
        total = (time.perf_counter() - start)
        return text, total, None


def _openai_do_request(headers, body, timeout, stream):
    """
    POST to OpenAI. If HTTP 400:
      - auto-switch max_tokens <-> max_completion_tokens if needed
      - drop response_format if unsupported
    Returns a Response with status OK or raises on error.
    """
    url = "https://api.openai.com/v1/chat/completions"

    def _post(b):
        return requests.post(url, headers=headers, json=b, stream=stream, timeout=timeout)

    r = _post(body)
    if r.status_code != 400:
        r.raise_for_status()
        return r

    # Try to adapt once
    try:
        err = r.json().get("error", {})
        msg = (err.get("message") or "").lower()
    except Exception:
        r.raise_for_status()
        return r

    adapted = False
    body2 = dict(body)

    if "max_tokens" in msg and "max_completion_tokens" in msg and "max_tokens" in body2:
        body2["max_completion_tokens"] = body2.pop("max_tokens")
        adapted = True

    if "response_format" in msg or ("json" in msg and "support" in msg):
        if "response_format" in body2:
            body2.pop("response_format", None)
            adapted = True

    if adapted:
        r2 = _post(body2)
        r2.raise_for_status()
        return r2
    else:
        r.raise_for_status()
        return r


def call_openai(
    model: str,
    prompt: str,
    max_tokens: int,
    timeout: int,
    measure_ttfb: bool = False
):
    """
    Calls OpenAI Chat Completions. Uses response_format=json_object when allowed.
    Returns: (text, total_sec, ttfb_sec_or_None)
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    messages = [{"role": "user", "content": prompt}]
    body = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "stream": bool(measure_ttfb),
    }
    # Some models (gpt-5*) prefer max_completion_tokens
    if model.startswith("gpt-5"):
        body["max_completion_tokens"] = max_tokens
    else:
        body["max_tokens"] = max_tokens

    start = time.perf_counter()
    if measure_ttfb:
        r = _openai_do_request(headers, body, timeout, stream=True)
        ttfb = None
        chunks = []
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("data: "):
                data = raw[len("data: "):].strip()
            else:
                data = raw.strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                delta = obj["choices"][0]["delta"].get("content", "")
            except Exception:
                delta = ""
            if delta and ttfb is None:
                ttfb = (time.perf_counter() - start)
            if delta:
                chunks.append(delta)
        total = (time.perf_counter() - start)
        return "".join(chunks).strip(), total, ttfb
    else:
        r = _openai_do_request(headers, body, timeout, stream=False)
        obj = r.json()
        total = (time.perf_counter() - start)
        text = (obj["choices"][0]["message"]["content"] or "").strip()
        return text, total, None


# ---------- Stats & CLI ----------

def pct_stats(xs: List[float]):
    xs = [x for x in xs if x is not None and math.isfinite(x)]
    if not xs:
        return ("NaN", "NaN", "NaN", "NaN")
    xs.sort()
    n = len(xs)

    def pct(p: float):
        if n == 1:
            return xs[0]
        i = int(p * (n - 1))
        return xs[i]

    p50 = pct(0.50)
    p90 = pct(0.90)
    mean = sum(xs) / n
    std = (sum((x - mean) ** 2 for x in xs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return (f"{p50 * 1000:.1f}", f"{p90 * 1000:.1f}", f"{mean * 1000:.1f}", f"{std * 1000:.1f}")


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--log", help="Path to log file for last ERROR")
    src.add_argument("--error", help="Explicit error line")
    ap.add_argument("--context-file", help="Optional file for context lines")
    ap.add_argument("--window", type=int, default=0, help="Context window size")
    ap.add_argument("--prompt-template", help="Template with {error_line} and optional {context}")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--ollama-model", default=os.environ.get("OLLAMA_MODEL", "llama3.2:1b"))
    ap.add_argument("--ollama-opts", default=os.environ.get("OLLAMA_OPTS", "{}"))
    ap.add_argument("--openai-model", default=os.environ.get("OPENAI_MODEL", "gpt-4o"))
    ap.add_argument("--openai-max-tokens", type=int, default=int(os.environ.get("OPENAI_MAX_TOKENS", "64")))
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--ttfb", action="store_true", help="Measure time-to-first-byte by streaming")
    ap.add_argument("--csv", help="Append per-run totals to CSV")

    args = ap.parse_args()

    if args.log:
        err_line, idx, lines = read_last_error_line(args.log)
        ctx_lines = window_context(lines, idx, args.window)
    else:
        err_line = args.error
        ctx_lines = []
        if args.context_file and os.path.exists(args.context_file):
            with open(args.context_file, 'r', errors='ignore') as f:
                ctx_lines = f.read().splitlines()[:args.window] if args.window > 0 else []

    prompt = render_prompt(args.prompt_template, err_line, ctx_lines)

    print("=== INPUT ===")
    print("ERROR:", err_line)
    print(f"Context lines: {len(ctx_lines)} (window={args.window})\n")

    ollama_totals, openai_totals = [], []
    ollama_ttfbs, openai_ttfbs = [], []
    last_ollama_txt, last_openai_txt = "", ""

    for i in range(args.runs):
        # Ollama
        o_txt, o_total, o_ttfb = call_ollama(
            args.ollama_url, args.ollama_model, prompt, args.ollama_opts, args.timeout, measure_ttfb=args.ttfb
        )
        ollama_totals.append(o_total)
        if args.ttfb and o_ttfb is not None:
            ollama_ttfbs.append(o_ttfb)

        # OpenAI
        a_txt, a_total, a_ttfb = call_openai(
            args.openai_model, prompt, args.openai_max_tokens, args.timeout, measure_ttfb=args.ttfb
        )
        openai_totals.append(a_total)
        if args.ttfb and a_ttfb is not None:
            openai_ttfbs.append(a_ttfb)

        if i == args.runs - 1:
            last_ollama_txt = o_txt
            last_openai_txt = a_txt

    op50, op90, omean, ostd = pct_stats(ollama_totals)
    ap50, ap90, amean, astd = pct_stats(openai_totals)
    print("=== RESULTS (latency) ===")
    print(f"Ollama total: p50={op50} ms p90={op90} ms mean={omean} ms | model={args.ollama_model}")
    print(f"OpenAI total: p50={ap50} ms p90={ap90} ms mean={amean} ms | model={args.openai_model}")
    if args.ttfb:
        otp50, otp90, otmean, _ = pct_stats(ollama_ttfbs)
        atp50, atp90, atmean, _ = pct_stats(openai_ttfbs)
        print(f"Ollama TTFB: p50={otp50} ms p90={otp90} ms mean={otmean} ms")
        print(f"OpenAI TTFB: p50={atp50} ms p90={atp90} ms mean={atmean} ms")
    print()

    def trim(s: str, n: int = 800):
        s = s or ""
        return s if len(s) <= n else s[:n] + "..."
    print("=== OLLAMA JSON ===")
    print(json.dumps({"raw": trim(last_ollama_txt)}, indent=2))
    print()
    print("=== OPENAI JSON ===")
    print(json.dumps({"raw": trim(last_openai_txt)}, indent=2))
    print()

    if args.csv:
        try:
            newfile = not os.path.exists(args.csv)
            with open(args.csv, 'a', newline='') as f:
                w = csv.writer(f)
                if newfile:
                    w.writerow(["engine", "total_ms", "model", "error_preview"])
                err_short = (err_line or "")[:120]
                for t in ollama_totals:
                    w.writerow(["ollama", f"{t*1000:.3f}", args.ollama_model, err_short])
                for t in openai_totals:
                    w.writerow(["openai", f"{t*1000:.3f}", args.openai_model, err_short])
            print(f"[written] {args.csv}")
        except Exception as e:
            print(f"[csv error] {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
