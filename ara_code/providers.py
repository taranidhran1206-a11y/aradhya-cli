"""Model providers for Aradhya Code.

History format (provider-neutral, JSON-safe so sessions can be saved):
  {"role": "user", "text": str}
  {"role": "assistant", "text": str, "tool_calls": [{"id", "name", "args", "sig"}]}
  {"role": "tool", "id": str, "name": str, "result": str}

Every provider's stream() yields events:
  ("text", str)            a piece of the reply
  ("tool_call", dict)      {"id", "name", "args", "sig"}
  ("usage", (in, out))     token counts for this request
"""
import base64
import json
import os
import time
import urllib.request
import uuid

GEMINI_FALLBACKS = ["gemini-flash-latest", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]


class ProviderError(Exception):
    pass


def _new_id():
    return "call_" + uuid.uuid4().hex[:10]


# ─────────────────────────── Gemini ───────────────────────────

class GeminiProvider:
    name = "gemini"

    def __init__(self, model=None, api_key=None, cred=None, name="gemini"):
        self.name = name
        if cred is None:
            key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            cred = {"key": key} if key else None
        if not cred:
            raise ProviderError("No Gemini key or Google sign-in yet. Run: ara setup")
        self.cred = cred
        self.api_key = cred.get("key")
        self.model = model or os.environ.get("ARA_MODEL") or GEMINI_FALLBACKS[0]
        self._client = None
        if self.api_key:  # a Google sign-in always goes over plain HTTPS
            try:
                from google import genai
                from google.genai import types
                self._client = genai.Client(api_key=self.api_key,
                                            http_options=types.HttpOptions(api_version="v1beta"))
            except ImportError:  # e.g. Termux, where google-genai's pydantic won't build: talk to the API directly
                self._client = None

    def _headers(self):
        from .engines import gemini_headers
        try:
            return gemini_headers(self.cred)
        except Exception as e:  # e.g. the Google sign-in expired
            raise ProviderError(str(e))

    def _contents(self, history):
        from google.genai import types
        out, pending = [], []

        def flush():
            if pending:
                out.append(types.Content(role="user", parts=list(pending)))
                pending.clear()

        for m in history:
            if m["role"] == "tool":
                pending.append(types.Part(function_response=types.FunctionResponse(
                    id=m.get("gid"), name=m["name"], response={"output": m["result"]})))
                continue
            flush()
            if m["role"] == "user":
                out.append(types.Content(role="user", parts=[types.Part.from_text(text=m["text"])]))
            else:
                parts = []
                if m.get("text"):
                    parts.append(types.Part.from_text(text=m["text"]))
                for tc in m.get("tool_calls", []):
                    p = types.Part(function_call=types.FunctionCall(id=tc.get("gid"), name=tc["name"], args=tc["args"]))
                    if tc.get("sig"):
                        p.thought_signature = base64.b64decode(tc["sig"])
                    parts.append(p)
                if parts:
                    out.append(types.Content(role="model", parts=parts))
        flush()
        return out

    def stream(self, history, system, tools, temperature=0.4):
        if self._client is None:
            yield from self._stream_rest(history, system, tools, temperature)
            return
        from google.genai import types
        decls = [types.FunctionDeclaration(name=t["name"], description=t["description"],
                                           parameters_json_schema=t["parameters"]) for t in tools]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=decls)] if decls else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=temperature,
        )
        contents = self._contents(history)
        order = [self.model] + [m for m in GEMINI_FALLBACKS if m != self.model]
        errors = []
        for attempt in range(3):
            busy = []
            for model in order:
                started = False
                try:
                    for chunk in self._client.models.generate_content_stream(
                            model=model, contents=contents, config=config):
                        if chunk.usage_metadata and chunk.usage_metadata.prompt_token_count:
                            u = chunk.usage_metadata
                            yield ("usage", (u.prompt_token_count or 0, u.candidates_token_count or 0))
                        if not chunk.candidates:
                            continue
                        content = chunk.candidates[0].content
                        for part in (content.parts if content and content.parts else []):
                            if part.thought:
                                continue
                            if part.function_call:
                                started = True
                                fc = part.function_call
                                sig = base64.b64encode(part.thought_signature).decode() if part.thought_signature else None
                                yield ("tool_call", {"id": fc.id or _new_id(), "gid": fc.id, "name": fc.name,
                                                     "args": dict(fc.args or {}), "sig": sig})
                            elif part.text:
                                started = True
                                yield ("text", part.text)
                    self.model = model  # stick with the one that works
                    return
                except Exception as e:  # noqa: BLE001 - try the next model
                    if started:
                        raise ProviderError(f"{model} stopped mid-answer: {e}")
                    msg = str(e)
                    errors.append(f"{model}: {msg[:200]}")
                    if "INVALID_ARGUMENT" in msg or "API key" in msg or "PERMISSION_DENIED" in msg:
                        raise ProviderError("Gemini refused the request.\n" + errors[-1])
                    if any(code in msg for code in ("429", "503", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
                                                     "DEADLINE", "timed out", "Connection")):
                        busy.append(model)  # worth another try after a pause
            if not busy:
                break
            order = busy
            time.sleep(4 * (attempt + 1))
        raise ProviderError("Gemini didn't answer (busy or out of quota). Try again in a minute, or /model another.\n"
                            + "\n".join(errors[-4:]))


    # ── same thing over plain HTTPS (no SDK) ──
    @staticmethod
    def _rest_contents(history):
        out, pending = [], []
        for m in history:
            if m["role"] == "tool":
                fr = {"name": m["name"], "response": {"output": m["result"]}}
                if m.get("gid"):
                    fr["id"] = m["gid"]
                pending.append({"functionResponse": fr})
                continue
            if pending:
                out.append({"role": "user", "parts": pending})
                pending = []
            if m["role"] == "user":
                out.append({"role": "user", "parts": [{"text": m["text"]}]})
            else:
                parts = [{"text": m["text"]}] if m.get("text") else []
                for tc in m.get("tool_calls", []):
                    fc = {"name": tc["name"], "args": tc["args"]}
                    if tc.get("gid"):
                        fc["id"] = tc["gid"]
                    part = {"functionCall": fc}
                    if tc.get("sig"):
                        part["thoughtSignature"] = tc["sig"]
                    parts.append(part)
                if parts:
                    out.append({"role": "model", "parts": parts})
        if pending:
            out.append({"role": "user", "parts": pending})
        return out

    def _stream_rest(self, history, system, tools, temperature):
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": self._rest_contents(history),
                "generationConfig": {"temperature": temperature}}
        if tools:
            body["tools"] = [{"functionDeclarations": [
                {"name": t["name"], "description": t["description"], "parametersJsonSchema": t["parameters"]}
                for t in tools]}]
        data = json.dumps(body).encode()
        order = [self.model] + [m for m in GEMINI_FALLBACKS if m != self.model]
        errors = []
        for attempt in range(3):
            busy = []
            for model in order:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **self._headers()})
                started = False
                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        for raw in resp:
                            line = raw.decode("utf-8", "replace").strip()
                            if not line.startswith("data:"):
                                continue
                            chunk = json.loads(line[5:])
                            u = chunk.get("usageMetadata") or {}
                            if u.get("promptTokenCount"):
                                yield ("usage", (u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)))
                            for cand in chunk.get("candidates", [])[:1]:
                                for part in (cand.get("content") or {}).get("parts", []):
                                    if part.get("thought"):
                                        continue
                                    if "functionCall" in part:
                                        started = True
                                        fc = part["functionCall"]
                                        yield ("tool_call", {"id": fc.get("id") or _new_id(), "gid": fc.get("id"),
                                                             "name": fc["name"], "args": fc.get("args") or {},
                                                             "sig": part.get("thoughtSignature")})
                                    elif part.get("text"):
                                        started = True
                                        yield ("text", part["text"])
                    self.model = model
                    return
                except urllib.error.HTTPError as e:
                    msg = f"{e.code} {e.read().decode('utf-8', 'replace')[:200]}"
                    errors.append(f"{model}: {msg}")
                    if e.code in (400, 401, 403):
                        hint = ("\nYour Google account may not be allowed to use this sign-in yet, or the sign-in expired. "
                                "Run: ara login google") if "oauth" in self.cred and e.code in (401, 403) else ""
                        raise ProviderError("Gemini refused the request.\n" + errors[-1] + hint)
                    if e.code in (429, 500, 503, 504):
                        busy.append(model)
                except Exception as e:  # noqa: BLE001
                    if started:
                        raise ProviderError(f"{model} stopped mid-answer: {e}")
                    errors.append(f"{model}: {e}")
                    busy.append(model)
            if not busy:
                break
            order = busy
            time.sleep(4 * (attempt + 1))
        raise ProviderError("Gemini didn't answer (busy or out of quota). Try again in a minute, or /model another.\n"
                            + "\n".join(errors[-4:]))


# ─────────────────── OpenAI-compatible (Hermes, OpenRouter, Ollama, LM Studio…) ───────────────────

class OpenAIProvider:
    name = "openai"

    def __init__(self, model=None, base_url=None, api_key=None, name="openai"):
        self.name = name
        self.base = (base_url or os.environ.get("ARA_BASE_URL") or "http://localhost:8642/v1").rstrip("/")
        self.key = api_key or os.environ.get("ARA_API_KEY") or os.environ.get("OPENAI_API_KEY") or "none"
        self.model = model or os.environ.get("ARA_MODEL") or "default"

    def _messages(self, history, system):
        msgs = [{"role": "system", "content": system}]
        for m in history:
            if m["role"] == "user":
                msgs.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                a = {"role": "assistant", "content": m.get("text") or None}
                if m.get("tool_calls"):
                    a["tool_calls"] = [{"id": tc["id"], "type": "function",
                                        "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                                       for tc in m["tool_calls"]]
                msgs.append(a)
            else:
                msgs.append({"role": "tool", "tool_call_id": m["id"], "content": m["result"]})
        return msgs

    def stream(self, history, system, tools, temperature=0.4):
        body = {
            "model": self.model, "stream": True, "temperature": temperature,
            "messages": self._messages(history, system),
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        if "anthropic.com" in self.base:  # Anthropic wants a reply length
            body["max_tokens"] = 16000
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self.key}
        if "openrouter.ai" in self.base:  # shows up as "Aradhya Code" in your OpenRouter activity
            headers.update({"HTTP-Referer": "https://taranidhran1206-a11y.github.io/unknown-project/",
                            "X-Title": "Aradhya Code"})
        req = urllib.request.Request(self.base + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=180)
        except Exception as e:
            from .engines import friendly_error
            raise ProviderError(f"{self.name} ({self.model}): {friendly_error(e)}")
        calls = {}
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                if obj.get("usage"):
                    u = obj["usage"]
                    yield ("usage", (u.get("prompt_tokens", 0), u.get("completion_tokens", 0)))
                for ch in obj.get("choices", []):
                    delta = ch.get("delta") or {}
                    if delta.get("content"):
                        yield ("text", delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        c = calls.setdefault(tc.get("index", 0), {"id": None, "name": "", "args": ""})
                        if tc.get("id"):
                            c["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            c["name"] += fn["name"]
                        if fn.get("arguments"):
                            c["args"] += fn["arguments"]
        for _, c in sorted(calls.items()):
            try:
                args = json.loads(c["args"] or "{}")
            except ValueError:
                args = {"_raw": c["args"]}
            yield ("tool_call", {"id": c["id"] or _new_id(), "name": c["name"], "args": args, "sig": None})


# ─────────────────────────── Scripted (tests) ───────────────────────────

class ScriptedProvider:
    """Replays canned turns. Each turn is a list of events; used by the test suite."""
    name = "scripted"
    model = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def stream(self, history, system, tools, temperature=0.4):
        self.seen.append(json.loads(json.dumps(history)))
        if not self.turns:
            yield ("text", "(no more scripted turns)")
            return
        for ev in self.turns.pop(0):
            if ev[0] == "sleep":
                time.sleep(ev[1])
                continue
            if ev[0] == "stream":  # type text out slowly
                for i in range(0, len(ev[1]), 6):
                    time.sleep(0.03)
                    yield ("text", ev[1][i:i + 6])
                continue
            yield tuple(ev)


def make_provider(kind=None, model=None, base_url=None):
    """Build the provider from flags, environment and ~/.aradhya/config.json. ProviderError("NOT_SET_UP")
    means nothing has been chosen yet (onboarding should run)."""
    from . import engines
    if (kind or os.environ.get("ARA_PROVIDER")) == "scripted":  # for demos and UI tests: ARA_SCRIPT=turns.json
        return ScriptedProvider(json.load(open(os.environ["ARA_SCRIPT"], encoding="utf-8")))
    try:
        engine, model, base_url = engines.resolve(kind, model, base_url)
    except ValueError as e:
        raise ProviderError(str(e))
    if engine is None:
        raise ProviderError("NOT_SET_UP")
    return provider_for(engine, model, base_url)


def provider_for(engine, model, base_url=None, cred=None):
    from . import engines
    cred = cred if cred is not None else engines.credential(engine)
    if engine.kind == "gemini":
        if not cred:
            raise ProviderError(f"{engine.name} isn't connected yet. Run: ara login {engine.id}")
        return GeminiProvider(model=model, cred=cred, name=engine.id)
    if not cred:
        raise ProviderError(f"No {engine.name} key yet. Run: ara login {engine.id}")
    return OpenAIProvider(model=model, base_url=base_url or engine.base, api_key=cred.get("key") or "none",
                          name=engine.id)
