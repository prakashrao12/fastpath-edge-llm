#!/usr/bin/env python3
"""
Quick single-run latency smoke test for local Ollama vs OpenAI, with Ollama tuning.
"""
import argparse, os, time, json
from typing import Tuple, Dict, Any
import requests

try:
    from openai import OpenAI  # >=1.x
except Exception:
    OpenAI = None

def call_ollama(base_url: str, model: str, prompt: str, opts: Dict[str, Any], timeout: int = 30) -> Tuple[str, float]:
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
    client = OpenAI(timeout=timeout)
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 1,
    }
    # Newer families (gpt-5 / o3 / o4…) expect max_completion_tokens instead of max_tokens
    if any(model.startswith(p) for p in ("gpt-5", "o3", "o4")):
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
    try:
        t0 = time.perf_counter()
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or ""), time.perf_counter() - t0
    except Exception as e:
        # Show server error bodies to make debugging easier
        raise

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="Say OK and nothing else.")
    ap.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--ollama-model", default=os.environ.get("OLLAMA_MODEL", "tinyllama"))
    ap.add_argument("--ollama-opts", default=os.environ.get("OLLAMA_OPTS", '{"temperature":0,"num_predict":4,"num_ctx":128,"num_thread":2,"keep_alive":-1}'))
    ap.add_argument("--openai-model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    ap.add_argument("--openai-max-tokens", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    try:
        opts = json.loads(args.ollama_opts)
    except Exception as e:
        raise SystemExit(f"Invalid --ollama-opts JSON: {e}")

    txt, t = call_ollama(args.ollama_url, args.ollama_model, args.prompt, opts, args.timeout)
    print(f"Ollama: {t*1000:.1f} ms\n---\n{txt}\n")

    try:
        a_txt, a_t = call_openai(args.openai_model, args.prompt, args.openai_max_tokens, args.timeout)
        print(f"OpenAI: {a_t*1000:.1f} ms\n---\n{a_txt}\n")
    except Exception as e:
        print(f"OpenAI call failed: {e}")

if __name__ == "__main__":
    main()
