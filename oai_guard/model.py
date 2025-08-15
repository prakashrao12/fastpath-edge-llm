# oai_guard/model.py
import re, json, sys, requests
from typing import List, Dict, Union
from .config import Config

def _gen_prompt(messages: List[Dict]) -> str:
    sys_txt, user_txt = [], []
    for m in messages:
        role = m.get("role", "user"); content = m.get("content", "")
        if role == "system": sys_txt.append(content)
        else: user_txt.append(f"{role.upper()}:\n{content}")
    out = ""
    if sys_txt: out += "\n".join(sys_txt).strip() + "\n\n"
    out += "You must reply with STRICT JSON only.\n\n" + "\n\n".join(user_txt).strip()
    return out

def _parse_keep_alive(v: Union[str, int]) -> Union[str, int]:
    if isinstance(v, int): return v
    v = str(v).strip()
    return -1 if v == "-1" else v  # allow "24h" etc.

def _stream_generate(payload: dict, base_url: str, timeout_sec: int) -> str:
    with requests.post(f"{base_url}/api/generate", json=payload,
                       stream=True, timeout=(10, max(timeout_sec, 600))) as r:
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            body = ""
            try: body = r.text
            except Exception: pass
            raise requests.HTTPError(f"{e} | server said: {body}") from e
        chunks, tok = [], 0
        print("[model] streaming…", file=sys.stderr)
        for line in r.iter_lines():
            if not line: continue
            try:
                chunk = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if "response" in chunk:
                chunks.append(chunk["response"]); tok += 1
                # progress ping without dumping JSON to stdout
                if tok % 10 == 0:
                    print(f"[model] tokens ~{tok}", file=sys.stderr)
            if chunk.get("done"):
                break
        print("[model] done", file=sys.stderr)
    return "".join(chunks)

def _nonstream_generate(payload: dict, base_url: str, timeout_sec: int) -> str:
    with requests.post(f"{base_url}/api/generate", json=payload, timeout=(10, timeout_sec)) as r:
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            body = ""
            try: body = r.text
            except Exception: pass
            raise requests.HTTPError(f"{e} | server said: {body}") from e
        obj = r.json()
        return obj.get("response", "")

def post_chat(messages: List[Dict], cfg: Config) -> str:
    prompt = _gen_prompt(messages)
    keep_alive = _parse_keep_alive(cfg.keep_alive)

    # Try streaming first (fast, shows progress)
    payload = {
        "model": cfg.model,
        "prompt": prompt,
        "stream": True,                 # first attempt
        # NOTE: no "format":"json" for max compatibility
        "options": {"num_predict": 256, "temperature": 0.2},
        "keep_alive": keep_alive,
    }
    try:
        return _stream_generate(payload, cfg.base_url, cfg.timeout_sec)
    except requests.HTTPError as e:
        if "400" in str(e):             # fallback to non-streaming if server rejects stream payload
            payload["stream"] = False
            return _nonstream_generate(payload, cfg.base_url, cfg.timeout_sec)
        raise

def extract_json(s: str) -> dict:
    s = s.strip()
    s = re.sub(r"^```json\s*|\s*```$", "", s, flags=re.I|re.M)
    first, last = s.find("{"), s.rfind("}")
    if first != -1 and last != -1 and last > first:
        return json.loads(s[first:last+1])
    return json.loads(s)

