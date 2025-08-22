#!/usr/bin/env python3
"""
ttfb_once.py - Measure streaming Time-To-First-Byte (TTFB)
for local Ollama vs OpenAI Chat Completions.

Usage:
  export OPENAI_API_KEY=sk-...
  python3 ttfb_once.py \
    --prompt "Say OK and nothing else." \
    --ollama-model tinyllama \
    --ollama-opts '{"temperature":0,"num_ctx":128,"num_thread":2,"keep_alive":-1}' \
    --openai-model gpt-4o --openai-max-tokens 8 --timeout 30
"""
import argparse, os, time, json, requests

try:
    from openai import OpenAI  # >=1.x
except Exception:
    OpenAI = None

def ttfb_ollama(base_url: str, model: str, prompt: str, opts_json: str, timeout: int = 30) -> float:
    """Return seconds to first streamed chunk from Ollama /api/generate."""
    opts = json.loads(opts_json) if opts_json else {}
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": True, "options": dict(opts)}
    # keep_alive must be top-level
    if "keep_alive" in payload["options"]:
        payload["keep_alive"] = payload["options"].pop("keep_alive")
    t0 = time.perf_counter()
    with requests.post(url, json=payload, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            # first non-empty chunk
            return time.perf_counter() - t0
    return float("nan")

def ttfb_openai(model: str, prompt: str, max_tokens: int, timeout: int = 30) -> float:
    """Return seconds to first streamed event from OpenAI chat.completions."""
    if OpenAI is None:
        raise RuntimeError("pip install openai>=1.0.0 and set OPENAI_API_KEY")
    client = OpenAI(timeout=timeout)
    t0 = time.perf_counter()
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role":"user","content":prompt}],
        temperature=0.0,
        max_tokens=max_tokens,
        stream=True,
    )
    # consume first event
    for _ in stream:
        break
    return time.perf_counter() - t0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="Say OK and nothing else.")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--ollama-model", default=os.environ.get("OLLAMA_MODEL", "tinyllama"))
    ap.add_argument("--ollama-opts", default=os.environ.get("OLLAMA_OPTS", '{"temperature":0,"num_ctx":128,"num_thread":2,"keep_alive":-1}'))
    ap.add_argument("--openai-model", default=os.environ.get("OPENAI_MODEL", "gpt-4o"))
    ap.add_argument("--openai-max-tokens", type=int, default=8)
    args = ap.parse_args()

    try:
        t1 = ttfb_ollama(args.ollama_url, args.ollama_model, args.prompt, args.ollama_opts, args.timeout)
        print(f"Ollama TTFB: {t1*1000:.1f} ms (model={args.ollama_model})")
    except Exception as e:
        print(f"Ollama TTFB failed: {e}")

    try:
        t2 = ttfb_openai(args.openai_model, args.prompt, args.openai_max_tokens, args.timeout)
        print(f"OpenAI TTFB: {t2*1000:.1f} ms (model={args.openai_model})")
    except Exception as e:
        print(f"OpenAI TTFB failed: {e}")

if __name__ == "__main__":
    main()
