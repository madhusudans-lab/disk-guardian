"""Optional AI through any OpenAI-compatible chat endpoint (Ollama, OpenRouter, Groq, Gemini, ...).
Off unless ai.base_url and ai.model are set. Only folder names and sizes are ever sent."""
import json
import os
import urllib.error
import urllib.request

from diskguardian import config
from diskguardian.util import log


def settings():
    a = config.load().get("ai") or {}
    key = os.environ.get("DISKGUARDIAN_AI_KEY") or a.get("api_key") or ""
    return a.get("base_url", "").rstrip("/"), a.get("model", ""), key


def configured():
    url, model, _ = settings()
    return bool(url and model)


def ask(prompt, timeout=120):
    url, model, key = settings()
    if not (url and model):
        return None
    body = json.dumps({"model": model, "temperature": 0.2,
                       "messages": [{"role": "system", "content": "You are a careful Windows storage expert. Be concise."},
                                    {"role": "user", "content": prompt}]}).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "DiskGuardian"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url + "/chat/completions", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data["choices"][0]["message"]["content"] or "").strip() or None
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
        log("ai call failed: %s" % e)
        return None
