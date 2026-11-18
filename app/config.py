"""Settings: stored in data/settings.json (editable in the UI). Environment variables override."""
import json
import os
import threading
from pathlib import Path

DATA = Path(os.environ.get("WA_DATA", Path(__file__).resolve().parent.parent / "data"))
LOCAL_MODELS = {
    "Qwen/Qwen2.5-0.5B-Instruct": "Ultra-Fast (0.5B int8/bfloat16, ~1 GB download, ~1.5 GB RAM, 3-5x faster)",
    "Qwen/Qwen2.5-1.5B-Instruct": "Quality (1.5B int8/bfloat16, ~3 GB download, ~3.5 GB RAM)",
    "HuggingFaceTB/SmolLM2-360M-Instruct": "Featherweight (360M, ~700 MB download, ~1 GB RAM, instant CPU)",
    "Qwen/Qwen2.5-1.5B-Instruct-GGUF": "GGUF 4-bit (1.5B Q4_K_M via llama-cpp, ~1 GB download, fastest CPU)",
}
PRESETS = {
    "groq": {"label": "Groq (recommended: free tier, fast)", "api_base": "https://api.groq.com/openai/v1",
             "api_model": "openai/gpt-oss-120b", "key_url": "https://console.groq.com/keys", "env": "GROQ_API_KEY"},
    "openai": {"label": "OpenAI", "api_base": "https://api.openai.com/v1", "api_model": "gpt-4o-mini",
               "key_url": "https://platform.openai.com/api-keys", "env": "OPENAI_API_KEY"},
    "xai": {"label": "xAI Grok", "api_base": "https://api.x.ai/v1", "api_model": "grok-3-mini",
            "key_url": "https://console.x.ai", "env": "XAI_API_KEY"},
    "ollama": {"label": "Ollama (local server)", "api_base": "http://localhost:11434/v1", "api_model": "llama3.1:8b",
               "key_url": "https://ollama.com", "env": None},
}
DEFAULTS = {
    "local_model": "Qwen/Qwen2.5-0.5B-Instruct",
    "local_quant": "bfloat16",
    "use_api": False,
    "api_base": "https://api.groq.com/openai/v1",
    "api_key": "",
    "api_model": "openai/gpt-oss-120b",
    "api_timeout": 90,
}
_LOCK = threading.Lock()


def settings_path():
    return DATA / "settings.json"


def load():
    s = dict(DEFAULTS)
    saved = {}
    p = settings_path()
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            s.update(saved)
        except Exception:
            pass
    env = {"local_model": "WA_LOCAL_MODEL", "api_base": "WA_API_BASE", "api_key": "WA_API_KEY", "api_model": "WA_API_MODEL"}
    for k, e in env.items():
        if os.environ.get(e):
            s[k] = os.environ[e]
    s["key_source"] = "settings" if s.get("api_key") else None
    if os.environ.get("WA_API_KEY"):
        s["key_source"] = "WA_API_KEY"
    # GROQ_API_KEY: if no key is configured, use Groq automatically.
    if not s.get("api_key") and os.environ.get("GROQ_API_KEY"):
        s["api_key"] = os.environ["GROQ_API_KEY"]
        s["key_source"] = "GROQ_API_KEY"
        if not saved.get("api_base") or saved.get("api_base") == PRESETS["openai"]["api_base"]:
            s["api_base"] = PRESETS["groq"]["api_base"]
            s["api_model"] = saved.get("api_model") if saved.get("api_base") == PRESETS["groq"]["api_base"] and saved.get("api_model") else PRESETS["groq"]["api_model"]
        if "use_api" not in saved:
            s["use_api"] = True
    if os.environ.get("WA_USE_API"):
        s["use_api"] = os.environ["WA_USE_API"] == "1"
    return s


def save(update):
    p = settings_path()
    s = dict(DEFAULTS)
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    if update.get("preset") in PRESETS:
        pr = PRESETS[update["preset"]]
        update = {"api_base": pr["api_base"], "api_model": pr["api_model"], **{k: v for k, v in update.items() if k not in ("api_base", "api_model") or v}}
    for k in DEFAULTS:
        if k in update and update[k] is not None:
            if k == "api_key" and update[k] == "********":
                continue  # masked value sent back unchanged
            s[k] = update[k]
    with _LOCK:
        DATA.mkdir(parents=True, exist_ok=True)
        settings_path().write_text(json.dumps({k: s[k] for k in DEFAULTS}, indent=2), encoding="utf-8")
    return load()


def public(s=None):
    s = dict(s or load())
    s["api_key"] = "********" if s.get("api_key") else ""
    s["local_models"] = LOCAL_MODELS
    s["presets"] = PRESETS
    s["groq_env"] = bool(os.environ.get("GROQ_API_KEY"))
    return s


def no_model():
    """WA_NO_MODEL=1 disables the local language model (rules-only rewriting; used in fast tests)."""
    return os.environ.get("WA_NO_MODEL") == "1"
