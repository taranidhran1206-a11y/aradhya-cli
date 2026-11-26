"""Setting Aradhya up: the first-run wizard (`ara setup`), switching brains (`ara model`, /model),
signing in and out (`ara login`, `ara logout`, `ara auth`) and the health check (`ara doctor`).

Every step can be undone with Esc, which goes back one step. Ctrl+C stops setup; nothing half-done is saved
except keys and sign-ins you finished.
"""
import os
import platform
import shutil
import sys
import threading
import time
from pathlib import Path

from rich.text import Text

from . import __version__, engines, login
from .ui import BLUE, FAINT, GOLD, GREEN, MUTED, RED

BACK = object()
STEPS_FULL = ["You", "Brain", "Connect", "Model", "Check", "Careful"]
MODE_CHOICES = [
    ("default", "Ask me first", "before she edits files or runs commands", "recommended"),
    ("accept-edits", "Edit freely", "she edits files without asking, asks before commands", ""),
    ("yolo", "Never ask", "she does everything herself. Careful!", ""),
]


class Cancelled(Exception):
    pass


# ─────────────────────────── small widgets ───────────────────────────

def pick(items, default=0, filterable=False, height=12):
    """Arrow-key list. items: dicts with label, hint, tag, tag_style, header (not selectable).
    Returns the chosen item's index, or BACK on Esc. Ctrl+C raises Cancelled. Typing filters when filterable."""
    selectable = [i for i, it in enumerate(items) if not it.get("header")]
    if not selectable:
        return BACK
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
    except ImportError:
        return _pick_plain(items)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _pick_plain(items)
    st = {"q": "", "cur": default if default in selectable else selectable[0], "top": 0}

    def visible():
        q = st["q"].lower()
        if not q:
            return list(range(len(items)))
        return [i for i in selectable if q in (items[i]["label"] + " " + items[i].get("hint", "")).lower()
                or items[i].get("always")]

    def choosable():
        return [i for i in visible() if not items[i].get("header")]

    def fix():
        ch = choosable()
        if ch and st["cur"] not in ch:
            st["cur"] = ch[0]

    kb = KeyBindings()

    def move(d):
        ch = choosable()
        if not ch:
            return
        st["cur"] = ch[(ch.index(st["cur"]) + d) % len(ch)] if st["cur"] in ch else ch[0]

    @kb.add("up")
    def _(e): move(-1)

    @kb.add("down")
    @kb.add("tab")
    def _(e): move(1)

    @kb.add("pageup")
    def _(e): move(-8)

    @kb.add("pagedown")
    def _(e): move(8)

    @kb.add("enter")
    def _(e):
        if st["cur"] in choosable():
            e.app.exit(result=st["cur"])

    @kb.add("escape", eager=True)
    @kb.add("left")
    def _(e):
        if st["q"]:
            st["q"] = ""
            fix()
        else:
            e.app.exit(result=BACK)

    @kb.add("c-c")
    def _(e): e.app.exit(result=Cancelled)

    if filterable:
        @kb.add("backspace")
        def _(e):
            st["q"] = st["q"][:-1]
            fix()

        @kb.add("<any>")
        def _(e):
            ch = e.data
            if ch and ch.isprintable() and len(ch) == 1:
                st["q"] += ch
                fix()

    label_w = min(30, max(len(items[i]["label"]) for i in selectable) + 2)
    hint_w = min(58, max((len(items[i].get("hint") or "") for i in selectable), default=0) + 2)
    tagged = any(items[i].get("tag") for i in selectable)

    def text():
        rows = visible()
        out = []
        if filterable:
            out.append((f"fg:{MUTED}", "   Type to search: "))
            out.append(("bold", st["q"] or ""))
            out.append((f"fg:{FAINT}", "" if st["q"] else "(start typing)"))
            out.append(("", "\n"))
        if not choosable():
            out.append((f"fg:{MUTED}", "   Nothing matches. Backspace to change it, Esc to clear.\n"))
            return out
        pos = rows.index(st["cur"]) if st["cur"] in rows else 0
        if pos < st["top"]:
            st["top"] = pos
        if pos >= st["top"] + height:
            st["top"] = pos - height + 1
        st["top"] = max(0, min(st["top"], max(0, len(rows) - height)))
        shown = rows[st["top"]:st["top"] + height]
        if st["top"] > 0:
            out.append((f"fg:{FAINT}", f"     ↑ {st['top']} more\n"))
        for i in shown:
            it = items[i]
            if it.get("header"):
                out.append((f"fg:{GOLD}", f"   {it['label']}\n"))
                continue
            on = i == st["cur"]
            out.append((f"fg:{BLUE} bold" if on else "", " ❯ " if on else "   "))
            out.append(("bold" if on else "", f"{it['label']:<{label_w}}"))
            hint = it.get("hint") or ""
            if hint or tagged:
                out.append((f"fg:{MUTED}", f"{hint:<{hint_w}}" if tagged else hint))
            if it.get("tag"):
                out.append((it.get("tag_style") or f"fg:{GREEN}", it["tag"]))
            out.append(("", "\n"))
        below = len(rows) - st["top"] - len(shown)
        if below > 0:
            out.append((f"fg:{FAINT}", f"     ↓ {below} more\n"))
        out.append((f"fg:{FAINT}", "   ↑↓ move · Enter choose · Esc back" + (" · type to search" if filterable else "")))
        return out

    app = Application(layout=Layout(Window(FormattedTextControl(text), dont_extend_height=True)),
                      key_bindings=kb, erase_when_done=True)
    res = app.run()
    if res is Cancelled:
        raise Cancelled()
    return res


def _pick_plain(items):
    idx = [i for i, it in enumerate(items) if not it.get("header")]
    for n, i in enumerate(idx, 1):
        it = items[i]
        print(f"  {n}. {it['label']}  {it.get('hint', '')}")
    while True:
        try:
            a = input("  Number (Enter to go back): ").strip()
        except (EOFError, KeyboardInterrupt):
            raise Cancelled()
        if not a:
            return BACK
        if a.isdigit() and 1 <= int(a) <= len(idx):
            return idx[int(a) - 1]


def ask(message, default="", secret=False):
    """One line of input. Esc returns BACK, Ctrl+C raises Cancelled."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings
    except ImportError:
        try:
            import getpass
            v = getpass.getpass(message) if secret else input(message)
        except (EOFError, KeyboardInterrupt):
            raise Cancelled()
        return v.strip() or default
    kb = KeyBindings()

    @kb.add("escape", eager=True)
    def _(e): e.app.exit(result=BACK)

    try:
        v = PromptSession(erase_when_done=True).prompt(
            FormattedText([(f"fg:{BLUE} bold", "   ❯ ")]) if not message else
            FormattedText([(f"fg:{MUTED}", message), (f"fg:{BLUE} bold", "❯ ")]),
            default=default, is_password=secret, key_bindings=kb)
    except (EOFError, KeyboardInterrupt):
        raise Cancelled()
    if v is BACK:
        return BACK
    return v.strip()


class Spinner:
    """A gold spinner on one line while she waits on the network."""

    FRAMES = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"]

    def __init__(self, console, text):
        self.console, self.text = console, text

    def __enter__(self):
        self._status = self.console.status(Text(self.text, style=MUTED), spinner="dots", spinner_style=GOLD)
        self._status.__enter__()
        return self

    def __exit__(self, *a):
        self._status.__exit__(*a)


# ─────────────────────────── the wizard ───────────────────────────

class Wizard:
    def __init__(self, ui, steps=None):
        self.ui, self.c = ui, ui.console
        cfg = engines.load_config()
        self.steps = steps or STEPS_FULL
        self.name = cfg.get("name") or os.environ.get("ARA_NAME") or ui.name
        current, model, url = None, None, None
        try:
            current, model, url = engines.resolve()
        except ValueError:
            pass
        self.engine = current
        self.model = model
        self.base_url = url
        self.mode = cfg.get("mode", "default")
        self.cred = None
        self.models = None
        self.checked = None

    # ── printing ──
    def done_line(self, step, value, style=""):
        t = Text("  ")
        t.append("✓ ", style=GREEN)
        t.append(f"{step:<9}", style=MUTED)
        t.append(value, style=style or "bold")
        self.c.print(t)

    def question(self, text, sub=None):
        self.c.print()
        t = Text("  ")
        t.append("◆ ", style=GOLD)
        t.append(text, style="bold")
        self.c.print(t)
        if sub:
            for line in sub if isinstance(sub, (list, tuple)) else [sub]:
                self.c.print(Text("    " + line, style=MUTED))

    def say(self, markup, kind=""):
        if kind == "url":
            self.c.print(f"    [{BLUE} underline]{markup}[/]", soft_wrap=True)
        elif kind == "dim":
            self.c.print(f"    [{FAINT}]{markup}[/]")
        else:
            self.c.print(f"    [{MUTED}]{markup}[/]")

    def warn(self, text):
        self.c.print(Text("    " + text, style=RED))

    # ── running ──
    def run(self):
        i = 0
        try:
            while i < len(self.steps):
                step = self.steps[i]
                r = getattr(self, "step_" + step.lower())()
                if r is BACK:
                    if i == 0:
                        return False
                    i -= 1
                    self.c.print(Text(f"  ↩ back to {self.steps[i]}", style=FAINT))
                    continue
                if isinstance(r, str) and r in self.steps:  # jump, e.g. Check → Brain
                    i = self.steps.index(r)
                    continue
                i += 1
        except Cancelled:
            self.c.print(Text("\n  Setup stopped. Run ara setup whenever you're ready.", style=MUTED))
            return False
        self.save()
        return True

    def save(self):
        changes = {"engine": self.engine.id, "model": self.model,
                   "base_url": self.base_url if self.engine.ask_url or self.base_url != self.engine.base else None,
                   "setup_version": __version__}
        if "You" in self.steps:
            changes["name"] = self.name
        if "Careful" in self.steps:
            changes["mode"] = self.mode
        engines.save_config(**changes)

    # ── steps ──
    def step_you(self):
        self.question("What should I call you?")
        v = ask("", default=self.name or "")
        if v is BACK:
            return BACK
        self.name = v or self.name or "friend"
        self.ui.name = self.name
        self.done_line("You", self.name)

    def step_brain(self):
        self.question("Which brain should I think with?",
                      "You can change this any time with ara model.")
        status = _local_status()
        items, group, default = [], None, None
        for e in engines.ENGINES:
            if e.group != group:
                group = e.group
                items.append({"label": group, "header": True})
            tag, style = "", None
            d = engines.describe(e) if not e.local and e.id != "custom" else None
            if d:
                tag = "✓ " + d
            elif e.id in status:
                tag, style = ("● running", f"fg:{GREEN}") if status[e.id] else ("not running", f"fg:{FAINT}")
            elif e.login == "google" and not login.google_client():
                tag, style = "needs one-time setup", f"fg:{FAINT}"
            items.append({"label": e.name, "hint": e.hint, "tag": tag, "tag_style": style, "engine": e})
            if self.engine is not None and e.id == self.engine.id:
                default = len(items) - 1
        if default is None:
            default = 1
        r = pick(items, default=default, height=18)
        if r is BACK:
            return BACK
        new = items[r]["engine"]
        if self.engine is None or new.id != self.engine.id:
            self.model = None
            self.base_url = new.base
        self.engine = new
        self.models = None
        self.done_line("Brain", new.name)

    def step_connect(self):
        e = self.engine
        if e.login == "google":
            return self._connect_google()
        if e.local or e.id == "custom":
            return self._connect_server()
        return self._connect_key()

    def _connect_google(self):
        cred = engines.credential(self.engine)
        if cred:
            email = cred["oauth"].get("email") or "your Google account"
            self.question("You're already signed in to Google.")
            r = pick([{"label": f"Use {email}"}, {"label": "Sign in again", "hint": "another account"}])
            if r is BACK:
                return BACK
            if r == 0:
                self.cred = cred
                self.done_line("Connect", f"signed in as {email}")
                return None
        while not login.google_client():
            self.question("Google sign-in needs a one-time setup.",
                          ["Google only lets apps sign you in with their own OAuth client. Make one (free, ~3 min):",
                           "1. console.cloud.google.com → turn on the \"Generative Language API\"",
                           "2. Google Auth platform → Audience: External, add your email as a test user",
                           "3. Clients → Create client → Desktop app → download the JSON",
                           f"Guide: {login.CLIENT_HELP}"])
            r = pick([{"label": "I have the JSON file", "hint": "point me to it"},
                      {"label": "Use a Gemini API key instead", "hint": "free from Google AI Studio"}])
            if r is BACK:
                return BACK
            if r == 1:
                self.engine = engines.get("gemini")
                self.done_line("Brain", self.engine.name)
                return self._connect_key()
            path = ask("    Path to the file: ")
            if path is BACK:
                continue
            try:
                login.import_google_client(path.strip().strip('"'))
                self.say("Got it. Saved to ~/.aradhya/google_client.json")
            except Exception as ex:  # noqa: BLE001
                self.warn(f"Couldn't use that file: {ex}")
        self.question("Sign in with Google")
        while True:
            try:
                email = login.google_login(self.say)
                break
            except login.LoginError as ex:
                self.warn(str(ex))
                r = pick([{"label": "Try again"}, {"label": "Use a Gemini API key instead"}])
                if r is BACK:
                    return BACK
                if r == 1:
                    self.engine = engines.get("gemini")
                    self.done_line("Brain", self.engine.name)
                    return self._connect_key()
        self.cred = engines.credential(self.engine)
        self.done_line("Connect", f"signed in as {email or 'your Google account'}")

    def _connect_key(self):
        e = self.engine
        cred = engines.credential(e)
        options = []
        if cred and cred.get("key"):
            where = "from your environment" if cred.get("from") == "env" else "saved"
            options.append({"label": f"Use the key …{cred['key'][-4:]}", "hint": where, "do": "keep"})
        if e.login == "openrouter":
            options.append({"label": "Sign in with OpenRouter", "hint": "opens your browser, no key to copy",
                            "do": "oauth"})
        options.append({"label": "Paste a key", "hint": e.key_url or "", "do": "paste"})
        self.question(f"How should I connect to {e.name}?")
        r = pick(options)
        if r is BACK:
            return BACK
        do = options[r]["do"]
        if do == "keep":
            self.cred = cred
            self.done_line("Connect", f"key …{cred['key'][-4:]}")
            return None
        if do == "oauth":
            self.question("Sign in with OpenRouter")
            try:
                key = login.openrouter_login(self.say)
            except login.LoginError as ex:
                self.warn(str(ex))
                return self.step_connect()
            self.cred = {"key": key}
            self.done_line("Connect", "signed in to OpenRouter")
            return None
        while True:
            self.question(f"Paste your {e.name} key", f"Get one at {e.key_url}" if e.key_url else None)
            key = ask("", secret=True)
            if key is BACK:
                return self.step_connect()
            if not key:
                continue
            cred = {"key": key}
            with Spinner(self.c, "Checking the key…"):
                try:
                    self.models = engines.list_models(e, self.base_url, cred)
                    ok, err = True, None
                except Exception as ex:  # noqa: BLE001
                    ok, err = False, ex
            if not ok and _is_auth_error(err):
                self.warn(engines.friendly_error(err) + ". Check it and paste it again.")
                continue
            engines.save_auth(e.id, {"type": "key", "key": key})
            self.cred = engines.credential(e)
            self.done_line("Connect", f"key …{key[-4:]} saved")
            if not ok:
                self.say(f"(I couldn't list the models: {engines.friendly_error(err)}. Carrying on.)", "dim")
            return None

    def _connect_server(self):
        e = self.engine
        url = self.base_url or e.base or ""
        if e.ask_url or not url:
            self.question(f"Where is {e.name}?",
                          "The address that ends in /v1, e.g. http://localhost:8642/v1 or http://<ec2-ip>:8642/v1")
            v = ask("", default=url)
            if v is BACK:
                return BACK
            url = v.rstrip("/")
        while True:
            with Spinner(self.c, f"Looking for {e.name} at {url}…"):
                up = engines.reachable(url, timeout=4)
            if up:
                break
            hint = {"ollama": "Start it with: ollama serve", "lmstudio": "In LM Studio, start the local server (Developer tab)",
                    "hermes": "Start it with: hermes gateway (API server on port 8642)"}.get(e.id, "")
            self.warn(f"Nothing answered at {url}. " + hint)
            r = pick([{"label": "Try again"}, {"label": "Use a different address"}])
            if r is BACK:
                return BACK
            if r == 1:
                v = ask("    Address: ", default=url)
                if v is BACK:
                    return BACK
                url = v.rstrip("/")
        self.base_url = url
        cred = engines.credential(e) or {"key": None}
        if e.id in ("hermes", "custom") and not cred.get("key"):
            try:
                engines.list_models(e, url, {"key": None})
            except Exception as ex:  # noqa: BLE001
                if _is_auth_error(ex):
                    self.question("It wants a key.")
                    key = ask("", secret=True)
                    if key is BACK:
                        return BACK
                    engines.save_auth(e.id, {"type": "key", "key": key})
                    cred = {"key": key}
        self.cred = cred
        self.done_line("Connect", url)

    def step_model(self):
        e = self.engine
        cred = self.cred or engines.credential(e) or {}
        if self.models is None:
            with Spinner(self.c, f"Seeing which models {e.name} has…"):
                try:
                    self.models = engines.list_models(e, self.base_url, cred)
                except Exception as ex:  # noqa: BLE001
                    self.models = []
                    self.say(f"Couldn't list the models ({engines.friendly_error(ex)}).", "dim")
        models = self.models
        best = engines.suggested(e, models)
        current = self.model if self.model in models else None
        if not models:
            self.question("Which model?", f"Type its name. Press Enter for {best}.")
            v = ask("", default=self.model or best)
            if v is BACK:
                return BACK
            self.model = v or best
            self.done_line("Model", self.model)
            return None
        self.question("Which model?", f"{len(models)} available. The first one is my pick for coding.")
        items = []
        for m in models:
            tag = "my pick" if m == best else ("current" if m == current else "")
            items.append({"label": m, "tag": tag, "tag_style": f"fg:{GOLD}" if m == best else f"fg:{MUTED}"})
        items.append({"label": "Type a model name…", "hint": "", "always": True, "typed": True})
        default = models.index(current) if current else 0
        r = pick(items, default=default, filterable=len(models) > 8)
        if r is BACK:
            return BACK
        if items[r].get("typed"):
            v = ask("    Model name: ", default=self.model or best)
            if v is BACK:
                return self.step_model()
            self.model = v or best
        else:
            self.model = items[r]["label"]
        self.done_line("Model", self.model)

    def step_check(self):
        from .providers import ProviderError, provider_for
        e = self.engine
        try:
            prov = provider_for(e, self.model, self.base_url, self.cred or engines.credential(e))
        except ProviderError as ex:
            self.warn(str(ex))
            return "Connect"
        reply, err, t0 = [], None, time.time()
        with Spinner(self.c, f"Saying hello with {self.model}…"):
            try:
                for kind, val in prov.stream([{"role": "user", "text": "Say hi to me in under eight words."}],
                                             f"You are Aradhya, a warm coding assistant. The user is {self.name}.",
                                             [], temperature=0.7):
                    if kind == "text":
                        reply.append(val)
                    if time.time() - t0 > 60:
                        break
            except Exception as ex:  # noqa: BLE001
                err = ex
        if err is None and "".join(reply).strip():
            self.model = getattr(prov, "model", self.model)
            said = " ".join("".join(reply).split())[:70]
            self.done_line("Check", f"“{said}”", style=f"italic {GOLD}")
            self.c.print(Text(f"             answered in {time.time() - t0:.1f}s", style=FAINT))
            return None
        self.warn("She couldn't answer: " + (str(err) if err else "the reply came back empty").splitlines()[0][:200])
        r = pick([{"label": "Try again"}, {"label": "Pick another model"}, {"label": "Pick another brain"},
                  {"label": "Skip the check", "hint": "save it anyway"}])
        if r is BACK or r == 1:
            return "Model"
        if r == 0:
            return "Check"
        if r == 2:
            return "Brain"
        return None

    def step_careful(self):
        self.question("How careful should I be?", "Shift+Tab changes this inside a session.")
        items = [{"label": label, "hint": hint, "tag": tag} for _, label, hint, tag in MODE_CHOICES]
        cur = next((i for i, m in enumerate(MODE_CHOICES) if m[0] == self.mode), 0)
        r = pick(items, default=cur)
        if r is BACK:
            return BACK
        self.mode = MODE_CHOICES[r][0]
        self.done_line("Careful", MODE_CHOICES[r][1].lower() + " · " + MODE_CHOICES[r][2])


def _is_auth_error(ex):
    import urllib.error
    return isinstance(ex, urllib.error.HTTPError) and ex.code in (400, 401, 403)


def _local_status():
    """Which local engines are answering right now (checked side by side, ~1.5s at most)."""
    out = {}

    def check(e):
        out[e.id] = engines.reachable(e.base)

    threads = [threading.Thread(target=check, args=(e,), daemon=True)
               for e in engines.ENGINES if e.id in ("ollama", "lmstudio", "hermes")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(2)
    return out


# ─────────────────────────── commands ───────────────────────────

def setup(ui, first_run=False):
    """`ara setup`. Returns True if she's ready to go."""
    if first_run:
        ui.setup_card("Hi, I'm Aradhya ✨", ["Let's get me ready. It takes about a minute.",
                                             "Esc goes back a step, Ctrl+C stops."])
    else:
        ui.setup_card("Let's set me up again", ["Esc goes back a step, Ctrl+C stops.",
                                                "Your sessions and project notes stay as they are."])
    w = Wizard(ui)
    if not w.run():
        return False
    summary(ui, w)
    return True


def summary(ui, w):
    c = ui.console
    c.print()
    c.print(Text.assemble(("  ✦ ", GOLD), ("All set", f"bold {GOLD}"),
                          (f" · saved to {_short(engines.CONFIG)}", MUTED)))
    c.print(Text("    Change things later: ", style=MUTED) + Text("ara model", style="bold")
            + Text(" · ", style=MUTED) + Text("ara login", style="bold") + Text(" · ", style=MUTED)
            + Text("ara doctor", style="bold") + Text(" · ", style=MUTED) + Text("ara setup", style="bold"))
    c.print()


def switch(ui):
    """`ara model` and /model with no name: pick a brain, connect it, pick a model, check it.
    Returns (engine, model, base_url) or None."""
    w = Wizard(ui, steps=["Brain", "Connect", "Model", "Check"])
    if w.engine is not None:
        ui.console.print(Text.assemble(("  Now: ", MUTED), (f"{w.engine.name}", "bold"), (f" · {w.model}", MUTED)))
    if not w.run():
        return None
    ui.console.print(Text.assemble(("  ✦ ", GOLD), ("Switched to ", ""), (f"{w.engine.name} · {w.model}", "bold")))
    ui.console.print()
    return w.engine, w.model, w.base_url


def pick_model(ui, engine, base_url, current):
    """/model inside a session: choose another model from the same brain, or go to a different brain.
    Returns ('model', name), ('brain', (engine, model, url)) or None."""
    w = Wizard(ui, steps=["Model"])
    w.engine, w.base_url, w.model = engine, base_url, current
    w.cred = engines.credential(engine)
    w.question(f"{engine.name} · now {current}")
    r = pick([{"label": "Another model", "hint": f"from {engine.name}"},
              {"label": "Another brain", "hint": "sign in or use a different service"}])
    if r is BACK:
        return None
    try:
        if r == 0:
            if w.step_model() is BACK:
                return None
            if engines.load_config().get("engine") == engine.id:
                engines.save_config(model=w.model)
            return ("model", w.model)
        res = switch(ui)
        return ("brain", res) if res else None
    except Cancelled:
        return None


def do_login(ui, engine_id=None, client_file=None):
    """`ara login [engine]`."""
    c = ui.console
    if client_file:
        try:
            cl = login.import_google_client(client_file)
            c.print(Text(f"  ✓ Google sign-in client saved (project {cl.get('project_id') or '?'})", style=GREEN))
        except Exception as ex:  # noqa: BLE001
            ui.error(f"Couldn't use that file: {ex}")
            return 1
        engine_id = engine_id or "google"
    w = Wizard(ui, steps=["Brain", "Connect"])
    try:
        if engine_id:
            e = engines.get(engine_id)
            if not e:
                ui.error(f"Unknown engine '{engine_id}'. Try: " + ", ".join(x.id for x in engines.ENGINES))
                return 1
            w.engine = e
            w.base_url = e.base
            if w.step_connect() is BACK:
                return 1
        else:
            if not w.run():
                return 1
    except Cancelled:
        c.print(Text("  Stopped.", style=MUTED))
        return 1
    cfg = engines.load_config()
    if cfg.get("engine") != w.engine.id:
        w.question(f"Think with {w.engine.name} from now on?")
        r = pick([{"label": "Yes, switch to it"}, {"label": "No, keep " + (engines.get(cfg.get('engine')).name
                                                                          if engines.get(cfg.get('engine')) else "what I have")}])
        if r == 0:
            w.steps = ["Model", "Check"]
            if w.run():
                c.print(Text.assemble(("  ✦ ", GOLD), (f"Switched to {w.engine.name} · {w.model}", "bold")))
    c.print()
    return 0


def do_logout(ui, engine_id=None):
    c = ui.console
    connected = [e for e in engines.ENGINES if engines.load_auth().get(e.id)]
    if not engine_id:
        if not connected:
            c.print(Text("  Nothing saved to sign out of.", style=MUTED))
            return 0
        items = [{"label": e.name, "hint": engines.describe(e) or "", "engine": e} for e in connected]
        try:
            r = pick(items)
        except Cancelled:
            return 1
        if r is BACK:
            return 1
        engine_id = items[r]["engine"].id
    e = engines.get(engine_id)
    if not e:
        ui.error(f"Unknown engine '{engine_id}'.")
        return 1
    if e.login == "google":
        login.google_logout()
    else:
        engines.save_auth(e.id, None)
    c.print(Text(f"  ✓ Signed out of {e.name}. Its saved key or sign-in is gone.", style=GREEN))
    if engines.env_key(e):
        c.print(Text(f"    (A key is still set in your environment: {', '.join(e.env)})", style=MUTED))
    return 0


def auth_status(ui):
    """`ara auth`: what she's connected to."""
    c = ui.console
    cfg = engines.load_config()
    c.print()
    c.print(Text.assemble(("  ✦ ", GOLD), ("Connections", f"bold {GOLD}")))
    for e in engines.ENGINES:
        if e.local or e.id == "custom":
            continue
        d = engines.describe(e)
        t = Text("  ")
        t.append("✓ " if d else "· ", style=GREEN if d else FAINT)
        t.append(f"{e.name:<16}", style="bold" if d else MUTED)
        t.append(d or "not connected", style="" if d else FAINT)
        if cfg.get("engine") == e.id:
            t.append("  ← in use", style=GOLD)
        c.print(t)
    if cfg.get("engine") in ("ollama", "lmstudio", "hermes", "custom"):
        c.print(Text(f"  ✓ {engines.get(cfg['engine']).name:<16}{cfg.get('base_url') or engines.get(cfg['engine']).base}  ← in use",
                     style=GOLD))
    c.print(Text("\n  ara login <name> to connect · ara logout <name> to remove\n", style=MUTED))
    return 0


def doctor(ui):
    """`ara doctor`: check everything she needs, and say how to fix what's wrong."""
    c = ui.console
    bad = 0

    def line(ok, what, detail="", fix=""):
        nonlocal bad
        t = Text("  ")
        if ok is True:
            t.append("✓ ", style=GREEN)
        elif ok is None:
            t.append("! ", style=GOLD)
        else:
            t.append("✗ ", style=RED)
            bad += 1
        t.append(f"{what:<16}", style="bold")
        t.append(detail, style=MUTED)
        c.print(t)
        if fix and ok is not True:
            c.print(Text("                    " + fix, style=GOLD if ok is None else RED))

    c.print()
    c.print(Text.assemble(("  ✦ ", GOLD), ("Aradhya's check-up", f"bold {GOLD}"), (f"  v{__version__}", MUTED)))
    py = sys.version_info
    line(py >= (3, 9), "Python", f"{platform.python_version()} · {sys.executable}", "Needs Python 3.9 or newer")
    exe = shutil.which("ara")
    line(True if exe else None, "ara command", exe or "not on PATH",
         "Open a new terminal, or run the installer again to add it to PATH")
    for mod, pkg, need, why in [("rich", "rich", True, ""), ("prompt_toolkit", "prompt_toolkit", True, ""),
                                ("google.genai", "google-genai", False, "optional: Gemini SDK (she works without it)"),
                                ("PIL", "pillow", False, "optional: sharp logo picture")]:
        try:
            __import__(mod)
            line(True, pkg, "installed")
        except ImportError:
            line(False if need else None, pkg, why or "missing", f"pip install {pkg}")
    try:
        engines.HOME.mkdir(parents=True, exist_ok=True)
        probe = engines.HOME / ".doctor"
        probe.write_text("ok")
        probe.unlink()
        line(True, "Her folder", _short(engines.HOME))
    except OSError as ex:
        line(False, "Her folder", str(ex), f"Check permissions on {engines.HOME}")
    try:
        engine, model, url = engines.resolve()
    except ValueError as ex:
        engine, model, url = None, None, None
        line(False, "Brain", str(ex), "Run: ara model")
    if engine is None:
        line(False, "Brain", "not set up yet", "Run: ara setup")
    else:
        line(True, "Brain", f"{engine.name} · {model}" + (f" · {url}" if engine.local or engine.ask_url else ""))
        cred = engines.credential(engine)
        if not cred:
            line(False, "Connected", "no key or sign-in", f"Run: ara login {engine.id}")
        else:
            line(True, "Connected", engines.describe(engine) or "ok")
            from .providers import provider_for
            t0 = time.time()
            reply, err = [], None
            with Spinner(c, "Asking her a quick question…"):
                try:
                    prov = provider_for(engine, model, url, cred)
                    for kind, val in prov.stream([{"role": "user", "text": "Reply with just: ok"}], "Be brief.", []):
                        if kind == "text":
                            reply.append(val)
                except Exception as ex:  # noqa: BLE001
                    err = ex
            if err is None and "".join(reply).strip():
                line(True, "Answering", f"{getattr(prov, 'model', model)} replied in {time.time() - t0:.1f}s")
            else:
                msg = (str(err) if err else "empty reply").splitlines()[0][:160]
                line(False, "Answering", msg, "Try ara model to pick another model, or ara login to reconnect")
    if engines.load_config().get("engine") == "google" or login.google_client():
        cl = login.google_client()
        line(True if cl else None, "Google client", (f"project {cl.get('project_id') or '?'}" if cl else "none"),
             "Only needed for Google sign-in: ara login google --client client_secret.json")
    from . import logo_img
    kind = logo_img.detect() if sys.stdout.isatty() else "not a terminal"
    line(True, "Terminal", f"{c.width} columns · {c.color_system or 'no'} colour · logo: {kind}")
    c.print()
    c.print(Text("  Everything looks good ✨\n" if not bad else f"  {bad} thing{'s' if bad > 1 else ''} to fix above.\n",
                 style=GOLD if not bad else RED))
    return 0 if not bad else 1


def _short(p):
    p = str(p)
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p
