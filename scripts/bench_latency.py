#!/usr/bin/env python3
"""
Latency benchmark: Local Ollama vs OpenAI Chat Completions (tunable)

- Measures end-to-end wall-clock latency (no streaming).
- Prints p50/p90/p95/mean/std and writes per-run CSV.
- Supports Ollama tuning via --ollama-opts (JSON) and OpenAI --openai-max-tokens.

Usage:
  export OPENAI_API_KEY=sk-...
  python3 bench_latency.py \
    --prompt "Say OK and nothing else." \
    --runs 9 --warmup 2 --timeout 30 \
    --ollama-model tinyllama \
    --ollama-opts '{"temperature":0,"num_predict":4,"num_ctx":128,"num_thread":2,"keep_alive":-1}' \
    --openai-model gpt-4o --openai-max-tokens 8 \
    --csv bench_results_heavy.csv
"""
import argparse, csv, json, math, os, statistics, time
from typing import List, Tuple, Dict, Any
import requests

try:
    from openai import OpenAI  # >=1.x
except Exception:
    OpenAI = None

def _quantile(values: List[float], q: float) -> float:
    if not values: return float('nan')
    s = sorted(values)
    idx = (len(s) - 1) * q
    lo, hi = int(idx // 1), int(-(-idx // 1))  # floor, ceil
    if lo == hi: return s[int(idx)]
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)

def call_ollama(base_url: str, model: str, prompt: str, opts: Dict[str, Any], timeout: int) -> Tuple[str, float]:
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False, "options": dict(opts)}
    # keep_alive must be top-level for Ollama
    if "keep_alive" in payload["options"]:
        payload["keep_alive"] = payload["options"].pop("keep_alive")
    t0 = time.perf_counter()
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    elapsed = time.perf_counter() - t0
    return r.json().get("response", ""), elapsed

def call_openai(model: str, prompt: str, max_tokens: int, timeout: int = 60):
    """
    Chat Completions call that adapts parameters by model family:
      - gpt-5*: omit temperature; use max_completion_tokens
      - o3*/o4*: allow temperature; use max_completion_tokens
      - others (e.g., gpt-4o): temperature + max_tokens
    """
    client = OpenAI(timeout=timeout)
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if model.startswith("gpt-5"):
        kwargs["max_completion_tokens"] = max_tokens
        # omit temperature entirely for gpt-5
    elif model.startswith(("o3", "o4")):
        kwargs["temperature"] = 0.0
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["temperature"] = 0.0
        kwargs["max_tokens"] = max_tokens

    t0 = time.perf_counter()
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or ""), time.perf_counter() - t0

def run_many(fn, runs: int, warmup: int) -> List[float]:
    # Warmups (ignored)
    for _ in range(warmup):
        try: fn()
        except Exception: pass
        time.sleep(0.15)
    # Timed runs
    out: List[float] = []
    for i in range(runs):
        try:
            _txt, t = fn()
            out.append(t)
            print(f"  run {i+1:02d}: {t*1000:.1f} ms")
        except Exception as e:
            print(f"  run {i+1:02d}: ERROR: {e}")
            out.append(float('nan'))
        time.sleep(0.15)
    return out

def summarize(label: str, xs: List[float]) -> dict:
    clean = [x for x in xs if math.isfinite(x)]
    if not clean:
        return {"label": label, "count": 0, "p50_ms": float('nan'), "p90_ms": float('nan'),
                "p95_ms": float('nan'), "mean_ms": float('nan'), "std_ms": float('nan')}
    return {
        "label": label, "count": len(clean),
        "p50_ms": _quantile(clean, 0.5) * 1000,
        "p90_ms": _quantile(clean, 0.9) * 1000,
        "p95_ms": _quantile(clean, 0.95) * 1000,
        "mean_ms": statistics.fmean(clean) * 1000,
        "std_ms": (statistics.pstdev(clean) if len(clean) > 1 else 0.0) * 1000,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="Say OK and nothing else.")
    ap.add_argument("--runs", type=int, default=9)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--ollama-model", default=os.environ.get("OLLAMA_MODEL", "tinyllama"))
    ap.add_argument("--ollama-opts", default=os.environ.get("OLLAMA_OPTS", '{"temperature":0,"num_predict":4,"num_ctx":128,"num_thread":2,"keep_alive":-1}'))
    ap.add_argument("--openai-model", default=os.environ.get("OPENAI_MODEL", "gpt-4o"))
    ap.add_argument("--openai-max-tokens", type=int, default=8)
    ap.add_argument("--csv", default="bench_results.csv")
    args = ap.parse_args()

    try:
        opts = json.loads(args.ollama_opts)
    except Exception as e:
        raise SystemExit(f"Invalid --ollama-opts JSON: {e}")

    print(f"[config] prompt={args.prompt!r}")
    print(f"[config] runs={args.runs} warmup={args.warmup} timeout={args.timeout}s")
    print(f"[config] ollama: {args.ollama_url} model={args.ollama_model} opts={opts}")
    print(f"[config] openai: model={args.openai_model} max_tokens={args.openai_max_tokens}")

    # Define callables
    _ollama = lambda: call_ollama(args.ollama_url, args.ollama_model, args.prompt, opts, args.timeout)
    _openai = lambda: call_openai(args.openai_model, args.prompt, args.openai_max_tokens, args.timeout)

    print("\n=== Ollama (local) ===")
    t_ollama = run_many(_ollama, args.runs, args.warmup)

    print("\n=== OpenAI (Chat Completions API) ===")
    t_openai = run_many(_openai, args.runs, args.warmup)

    s1, s2 = summarize("ollama", t_ollama), summarize("openai", t_openai)

    print("\n--- Summary (ms) ---")
    for s in (s1, s2):
        print(f"{s['label']:7s} | n={s['count']:2d}  p50={s['p50_ms']:.1f}  p90={s['p90_ms']:.1f}  p95={s['p95_ms']:.1f}  mean={s['mean_ms']:.1f}  std={s['std_ms']:.1f}")

    with open(args.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["engine", "run_index", "latency_ms"])
        for i, t in enumerate(t_ollama, 1): w.writerow(["ollama", i, f"{t*1000:.3f}"])
        for i, t in enumerate(t_openai, 1): w.writerow(["openai", i, f"{t*1000:.3f}"])
    print(f"\n[written] {args.csv}")

if __name__ == "__main__":
    main()
