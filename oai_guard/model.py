#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from dataclasses import dataclass
from typing import Any, Dict, List
import os, json, requests

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

@dataclass
class Config:
    engine: str = os.environ.get("OAI_ENGINE", "openai")   # 'openai' | 'ollama'
    # OpenAI
    openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o")
    openai_timeout: int = int(os.environ.get("OPENAI_TIMEOUT", "60"))
    openai_max_tokens: int = int(os.environ.get("OPENAI_MAX_TOKENS", "256"))
    openai_temperature: float = float(os.environ.get("OPENAI_TEMPERATURE", "0"))
    # Ollama
    ollama_url: str = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")
    ollama_timeout: int = int(os.environ.get("OLLAMA_TIMEOUT", "60"))
    ollama_opts_json: str = os.environ.get(
        "OLLAMA_OPTS",
        '{"temperature":0,"num_predict":128,"num_ctx":256,"num_thread":4,"keep_alive":-1}'
    )

_JSON_SCHEMA = {
    "name": "triage_plan",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "causes": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "diagnostics_cmds": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "fix_cmds": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "risk_level": {"type": "string", "enum": ["low","medium","high"]},
            "need_human_review": {"type": "boolean"}
        },
        "required": ["summary","diagnostics_cmds","risk_level","need_human_review"],
        "additionalProperties": False
    },
    "strict": True,
}

def _openai_chat(messages: List[Dict[str, str]], cfg: Config) -> str:
    """
    Prefer Chat Completions with response_format enforcing JSON.
    Falls back gracefully if not supported by the model.
    """
    if OpenAI is None:
        raise RuntimeError("Install openai: pip install openai>=1.0.0")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY env var")

    client = OpenAI(timeout=cfg.openai_timeout)

    def _kwargs(stream: bool, use_schema: bool):
        kwargs = {
            "model": cfg.openai_model,
            "messages": messages,
            "stream": stream,
        }
        # token/temperature knobs
        if cfg.openai_model.startswith("gpt-5"):
            kwargs["max_completion_tokens"] = cfg.openai_max_tokens
        elif cfg.openai_model.startswith(("o3","o4")):
            kwargs["temperature"] = cfg.openai_temperature
            kwargs["max_completion_tokens"] = cfg.openai_max_tokens
        else:
            kwargs["temperature"] = cfg.openai_temperature
            kwargs["max_tokens"] = cfg.openai_max_tokens
        # ask for JSON
        if use_schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": _JSON_SCHEMA}
        else:
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    # Try strict json_schema first, then json_object, then no response_format.
    for rf in ("schema","object","none"):
        try:
            if rf == "schema":
                resp = client.chat.completions.create(**_kwargs(stream=False, use_schema=True))
            elif rf == "object":
                resp = client.chat.completions.create(**_kwargs(stream=False, use_schema=False))
            else:
                kw = _kwargs(stream=False, use_schema=False)
                kw.pop("response_format", None)
                resp = client.chat.completions.create(**kw)
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            continue

    return ""  # last resort

def _ollama_chat(messages: List[Dict[str, str]], cfg: Config) -> str:
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        parts.append(f"{role.upper()}:\n{content}")
    prompt = "\n\n".join(parts) + "\n\nReturn ONLY JSON."

    try:
        opts = json.loads(cfg.ollama_opts_json)
    except Exception:
        opts = {}

    payload = {
        "model": cfg.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": opts,
        "format": "json",
    }
    if "keep_alive" in payload["options"]:
        payload["keep_alive"] = payload["options"].pop("keep_alive")

    url = f"{cfg.ollama_url.rstrip('/')}/api/generate"
    r = requests.post(url, json=payload, timeout=cfg.ollama_timeout)
    r.raise_for_status()
    obj = r.json()
    return (obj.get("response") or "").strip()

def post_chat(messages: List[Dict[str, str]], cfg: Config) -> str:
    if cfg.engine == "openai":
        return _openai_chat(messages, cfg)
    elif cfg.engine == "ollama":
        return _ollama_chat(messages, cfg)
    else:
        raise ValueError(f"Unknown engine: {cfg.engine}")
