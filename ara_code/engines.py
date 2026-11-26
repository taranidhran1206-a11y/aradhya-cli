"""The brains Aradhya can think with, where her settings live, and how each one signs in.

~/.aradhya/config.json   which engine and model she uses, your name, how careful she is
~/.aradhya/auth.json     keys and sign-ins (readable only by you)

Settings are looked up in this order: command-line flag, environment variable (including ~/.aradhya/.env),
config.json, then the engine's default.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("ARA_HOME", Path.home() / ".aradhya"))
CONFIG = HOME / "config.json"
AUTH = HOME / "auth.json"


class Engine:
    def __init__(self, id, name, hint, group, kind, base=None, env=(), key_url=None, default_model=None,
                 prefer=(), skip=(), login=None, local=False, ask_url=False):
        self.id, self.name, self.hint, self.group, self.kind = id, name, hint, group, kind
        self.base, self.env, self.key_url = base, tuple(env), key_url
        self.default_model, self.prefer, self.skip = default_model, tuple(prefer), tuple(skip)
        self.login, self.local, self.ask_url = login, local, ask_url

    def __repr__(self):
        return f"Engine({self.id})"


GEMINI_PREFER = (r"^gemini-flash-latest$", r"^gemini-[\d.]+-flash$", r"^gemini-pro-latest$", r"^gemini-[\d.]+-pro$")
GEMINI_SKIP = (r"embedding", r"aqa", r"imagen", r"veo", r"tts", r"image", r"live", r"audio", r"learnlm", r"gemma",
               r"exp", r"preview-\d\d-\d\d", r"robotics", r"computer-use", r"nano")
CHAT_SKIP = (r"embed", r"whisper", r"tts", r"audio", r"realtime", r"transcribe", r"dall-e", r"image", r"moderation",
             r"search", r"davinci", r"babbage", r"guard", r"rerank", r"vision-preview", r"sora", r"ocr")

ALWAYS_SKIP = (r"embed", r"whisper", r"moderation", r"rerank", r"^tts-")

ENGINES = [
    # Sign in with the browser
    Engine("google", "Google Gemini", "sign in with Google, no key to copy", "Sign in with your browser",
           "gemini", login="google", default_model="gemini-flash-latest", prefer=GEMINI_PREFER, skip=GEMINI_SKIP),
    Engine("openrouter", "OpenRouter", "sign in · Claude, GPT, Gemini, Llama, Hermes and 300+ more",
           "Sign in with your browser", "openai", base="https://openrouter.ai/api/v1", env=("OPENROUTER_API_KEY",),
           key_url="https://openrouter.ai/keys", login="openrouter", default_model="openrouter/auto",
           prefer=(r"^anthropic/claude-sonnet", r"^google/gemini-[\d.]+-flash$", r"^openai/gpt-5[\d.]*$",
                   r"^qwen/qwen[\d.]*-coder", r"^deepseek/deepseek-chat", r"^nousresearch/hermes-4",
                   r"^meta-llama/llama-[\d.]+-70b", r"^x-ai/grok-code")),
    # Paste a key
    Engine("gemini", "Gemini API key", "free key from Google AI Studio", "Paste a key", "gemini",
           env=("GEMINI_API_KEY", "GOOGLE_API_KEY"), key_url="https://aistudio.google.com/apikey",
           default_model="gemini-flash-latest", prefer=GEMINI_PREFER, skip=GEMINI_SKIP),
    Engine("openai", "OpenAI", "GPT models", "Paste a key", "openai", base="https://api.openai.com/v1",
           env=("OPENAI_API_KEY",), key_url="https://platform.openai.com/api-keys", default_model="gpt-5-mini",
           prefer=(r"^gpt-5[\d.]*-mini$", r"^gpt-5[\d.]*$", r"^gpt-5[\d.]*-codex", r"^gpt-4\.1$", r"^o\d-mini$"),
           skip=CHAT_SKIP + (r"^gpt-3", r"instruct", r"-\d{4}-\d\d-\d\d$", r"chatgpt", r"^codex-mini")),
    Engine("anthropic", "Anthropic", "Claude models", "Paste a key", "openai", base="https://api.anthropic.com/v1",
           env=("ANTHROPIC_API_KEY",), key_url="https://console.anthropic.com/settings/keys",
           default_model="claude-sonnet-4-5", prefer=(r"^claude-sonnet", r"^claude-opus", r"^claude-haiku")),
    Engine("nous", "Nous Portal", "Hermes models from Nous Research", "Paste a key", "openai",
           base="https://inference-api.nousresearch.com/v1", env=("NOUS_API_KEY",),
           key_url="https://portal.nousresearch.com", default_model="Hermes-4-70B",
           prefer=(r"hermes-4-405b", r"hermes-4-70b", r"hermes")),
    Engine("groq", "Groq", "very fast open models", "Paste a key", "openai", base="https://api.groq.com/openai/v1",
           env=("GROQ_API_KEY",), key_url="https://console.groq.com/keys", default_model="openai/gpt-oss-120b",
           prefer=(r"gpt-oss-120b", r"llama-3\.3-70b", r"kimi", r"qwen"), skip=CHAT_SKIP),
    Engine("deepseek", "DeepSeek", "DeepSeek chat and reasoner", "Paste a key", "openai",
           base="https://api.deepseek.com/v1", env=("DEEPSEEK_API_KEY",), key_url="https://platform.deepseek.com/api_keys",
           default_model="deepseek-chat", prefer=(r"^deepseek-chat$", r"^deepseek-reasoner$")),
    Engine("xai", "xAI", "Grok models", "Paste a key", "openai", base="https://api.x.ai/v1", env=("XAI_API_KEY",),
           key_url="https://console.x.ai", default_model="grok-code-fast-1",
           prefer=(r"^grok-code", r"^grok-4", r"^grok-3$"), skip=CHAT_SKIP),
    Engine("mistral", "Mistral", "Devstral, Codestral, Mistral Large", "Paste a key", "openai",
           base="https://api.mistral.ai/v1", env=("MISTRAL_API_KEY",), key_url="https://console.mistral.ai/api-keys",
           default_model="devstral-medium-latest",
           prefer=(r"^devstral.*latest$", r"^codestral-latest$", r"^mistral-large-latest$", r"^mistral-medium-latest$"),
           skip=CHAT_SKIP + (r"-\d{4}$",)),
    # On your machine (or your server)
    Engine("ollama", "Ollama", "models running on this computer", "On your machine or server", "openai",
           base="http://localhost:11434/v1", local=True, default_model="qwen2.5-coder",
           prefer=(r"coder", r"qwen", r"llama", r"hermes"), skip=(r"embed",)),
    Engine("lmstudio", "LM Studio", "models running in LM Studio", "On your machine or server", "openai",
           base="http://localhost:1234/v1", local=True, default_model="default", skip=(r"embed",)),
    Engine("hermes", "Hermes Agent", "your Hermes API server, here or on EC2", "On your machine or server", "openai",
           base="http://localhost:8642/v1", env=("ARA_API_KEY",), local=True, ask_url=True, default_model="default"),
    Engine("custom", "Custom", "any OpenAI-compatible address", "On your machine or server", "openai",
           env=("ARA_API_KEY",), ask_url=True, default_model="default"),
]
BY_ID = {e.id: e for e in ENGINES}
ALIASES = {"google-gemini": "google", "gemini-oauth": "google", "claude": "anthropic", "grok": "xai",
           "lm-studio": "lmstudio", "openai-compatible": "custom"}


def get(engine_id):
    engine_id = (engine_id or "").strip().lower()
    return BY_ID.get(ALIASES.get(engine_id, engine_id))


# ─────────────────────────── files ───────────────────────────

def _read(path):
    try:
        return json.loads(path.read_text("utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _write(path, data, private=False):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), "utf-8")
    if private:
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, path)


def load_config():
    return _read(CONFIG)


def save_config(**changes):
    cfg = load_config()
    for k, v in changes.items():
        if v is None:
            cfg.pop(k, None)
        else:
            cfg[k] = v
    _write(CONFIG, cfg)
    return cfg


def load_auth():
    return _read(AUTH)


def save_auth(engine_id, entry):
    auth = load_auth()
    if entry is None:
        auth.pop(engine_id, None)
    else:
        entry = dict(entry, saved=int(time.time()))
        auth[engine_id] = entry
    _write(AUTH, auth, private=True)


# ─────────────────────────── credentials ───────────────────────────

def env_key(engine):
    for name in engine.env:
        if os.environ.get(name):
            return os.environ[name]
    return None


def credential(engine):
    """What she'd use to talk to this engine right now: {'key': …}, {'oauth': …} or None."""
    stored = load_auth().get(engine.id) or {}
    if engine.login == "google":
        return {"oauth": stored} if stored.get("refresh_token") else None
    key = env_key(engine) or stored.get("key")
    if key:
        return {"key": key, "from": "env" if env_key(engine) else "saved", "who": stored.get("who")}
    if engine.local or engine.id == "custom":
        return {"key": None}
    return None


def describe(engine):
    """One line for status screens: who she's signed in as, which key, or what's missing."""
    cred = credential(engine)
    if engine.login == "google":
        return ("signed in as " + (cred["oauth"].get("email") or "your Google account")) if cred else None
    if not cred:
        return None
    if cred.get("key"):
        how = "from your environment" if cred.get("from") == "env" else "saved"
        who = f" ({cred['who']})" if cred.get("who") else ""
        return f"key …{cred['key'][-4:]} {how}{who}"
    return "no key needed"


def mask(key):
    return ("…" + key[-4:]) if key and len(key) > 8 else "set"


# ─────────────────────────── settings ───────────────────────────

def resolve(provider=None, model=None, base_url=None):
    """Work out (engine, model, base_url) from flags, environment and config.json. Engine is None if
    nothing is set up yet."""
    cfg = load_config()
    eid = provider or os.environ.get("ARA_PROVIDER")
    url = base_url or os.environ.get("ARA_BASE_URL")
    if eid == "openai" and url:  # old meaning: any OpenAI-compatible server
        eid = "custom"
    if not eid and url:
        eid = "custom"
    if not eid:
        eid = cfg.get("engine")
    if not eid and (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        eid = "gemini"  # set up before onboarding existed
    engine = get(eid) if eid else None
    if eid and not engine:
        raise ValueError(f"Unknown engine '{eid}'. Try one of: {', '.join(e.id for e in ENGINES)}")
    same = engine is not None and cfg.get("engine") == engine.id
    model = model or os.environ.get("ARA_MODEL") or (cfg.get("model") if same else None)
    url = url or (cfg.get("base_url") if same else None)
    if engine:
        model = model or engine.default_model
        url = url or engine.base
    return engine, model, url


# ─────────────────────────── talking to the engines ───────────────────────────

def _http(url, headers=None, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def gemini_headers(cred):
    """Request headers for the Gemini API: a key, or a Google sign-in (refreshed when needed)."""
    if "oauth" in cred:
        from . import login
        token, _project = login.google_access_token()
        h = {"Authorization": "Bearer " + token}
        # Usage is counted against the sign-in client's own Cloud project. Naming a quota project would make
        # Google demand that every user be a member of it, so only do it when asked to.
        if os.environ.get("ARA_GOOGLE_QUOTA_PROJECT"):
            h["x-goog-user-project"] = os.environ["ARA_GOOGLE_QUOTA_PROJECT"]
        return h
    return {"x-goog-api-key": cred["key"]}


def list_models(engine, base_url=None, cred=None):
    """The model names this engine offers, best first. Raises on network or auth trouble."""
    cred = cred if cred is not None else (credential(engine) or {})
    if engine.kind == "gemini":
        data = _http("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", gemini_headers(cred))
        names = [m["name"].split("/", 1)[-1] for m in data.get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    elif engine.id == "anthropic":
        data = _http("https://api.anthropic.com/v1/models?limit=100",
                     {"x-api-key": cred.get("key") or "", "anthropic-version": "2023-06-01"})
        names = [m["id"] for m in data.get("data", [])]
    else:
        base = (base_url or engine.base or "").rstrip("/")
        headers = {"Authorization": "Bearer " + cred["key"]} if cred.get("key") else {}
        data = _http(base + "/models", headers)
        items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
        names = []
        for m in items or []:
            mid = m.get("id") or m.get("name") if isinstance(m, dict) else str(m)
            if not mid:
                continue
            if engine.id == "openrouter" and "tools" not in (m.get("supported_parameters") or ["tools"]):
                continue  # she needs tool calling to read and edit files
            names.append(mid)
    return rank(engine, names)


def rank(engine, names):
    """Drop models that can't chat, put the engine's best coding models first, keep the rest in order."""
    skip = engine.skip + ALWAYS_SKIP
    names = [n for n in dict.fromkeys(names) if not any(re.search(s, n, re.I) for s in skip)]
    top = []
    for pat in engine.prefer:
        for n in names:
            if n not in top and re.search(pat, n, re.I):
                top.append(n)
                break
    rest = sorted((n for n in names if n not in top), key=str.lower)
    return top + rest


def suggested(engine, models):
    return models[0] if models else engine.default_model


def reachable(base_url, timeout=1.5):
    """True if something answers at this address (for Ollama / LM Studio / Hermes on this machine)."""
    try:
        urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=timeout).close()
        return True
    except urllib.error.HTTPError as e:
        return e.code in (401, 403)  # it's there, it just wants a key
    except Exception:
        return False


def friendly_error(e):
    """Turn an HTTP or network error into one plain sentence."""
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        detail = ""
        try:
            j = json.loads(body)
            err = j.get("error", j)
            detail = (err.get("message") if isinstance(err, dict) else str(err)) or ""
        except ValueError:
            detail = body.strip()[:160]
        detail = " (" + detail.strip()[:160] + ")" if detail else ""
        if e.code in (401, 403):
            return "The key or sign-in was refused" + detail
        if e.code == 404:
            return "That address or model wasn't found" + detail
        if e.code == 429:
            return "Out of quota or rate limited for now" + detail
        return f"The server answered {e.code}" + detail
    if isinstance(e, urllib.error.URLError):
        return f"Couldn't reach it ({e.reason})"
    return str(e) or e.__class__.__name__
