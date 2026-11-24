"""Aradhya Code: Aradhya as a coding agent in your terminal.

  ara                      start a session in this folder
  ara "fix the failing test"   start with a request
  ara -p "explain this repo"   answer once and exit (for scripts)
  ara -c                   continue the last session in this folder
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__
from .agent import Agent
from .providers import ProviderError, make_provider
from .tools import ToolBox
from .ui import TerminalUI, GOLD, BLUE, MUTED, RED, FAINT

HOME = Path(os.environ.get("ARA_HOME", Path.home() / ".aradhya"))
SESSIONS = HOME / "sessions"
MODES = ["default", "accept-edits", "yolo"]

HELP = """[bold]Commands[/bold]
  /help              this help
  /clear             start a fresh conversation
  /compact           summarize the conversation to free up context
  /init              write an ARADHYA.md describing this project (her project memory)
  /mode [name]       default (asks first) · accept-edits · yolo (never asks)
  /model [name]      show or switch the model
  /leo, /aradhya     switch persona
  /resume            pick an earlier session from this folder
  /todos             show the task list
  /status            model, folder, tokens used
  /exit              quit

[bold]Keys[/bold]
  Enter send · Alt+Enter new line · Shift+Tab change mode · Esc interrupt her
  @ pick a file · ? shortcuts · Ctrl+C clear input · Ctrl+C twice quit
  Start a line with [bold]![/bold] to run a shell command yourself, e.g. [bold]!git status[/bold]
"""

INIT_PROMPT = (
    "Explore this project and write ARADHYA.md in the working directory: a short guide for future you. "
    "Include what the project is, how to build/run/test it (exact commands), the layout of important "
    "folders, code style conventions you can see, and gotchas. Keep it under 80 lines. If ARADHYA.md "
    "already exists, improve it instead of replacing good content.")


def load_env():
    """Read KEY=value lines from .env files: ~/.aradhya/.env, the Aradhya repo, then the current folder."""
    candidates = [HOME / ".env", Path(__file__).resolve().parent.parent / ".env", Path.cwd() / ".env"]
    for f in candidates:
        if not f.exists():
            continue
        for line in f.read_text("utf-8", "replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v and "your-" not in v:
                    os.environ.setdefault(k.strip(), v)


# ─────────────────────────── sessions ───────────────────────────

def save_session(path, agent, cwd):
    SESSIONS.mkdir(parents=True, exist_ok=True)
    first = next((m["text"] for m in agent.history if m["role"] == "user"), "")
    data = {"cwd": str(cwd), "updated": time.time(), "title": first[:80], "persona": agent.persona,
            "history": agent.history, "tokens": [agent.tokens_in, agent.tokens_out]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    tmp.replace(path)


def list_sessions(cwd):
    out = []
    if not SESSIONS.exists():
        return out
    for f in SESSIONS.glob("*.json"):
        try:
            d = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if Path(d.get("cwd", "")) == Path(cwd):
            out.append((f, d))
    out.sort(key=lambda x: x[1].get("updated", 0), reverse=True)
    return out


def new_session_path():
    return SESSIONS / (datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")


# ─────────────────────────── input ───────────────────────────

COMMANDS = [
    ("/help", "Show commands and keys"), ("/clear", "Start a fresh conversation"),
    ("/compact", "Summarize the chat to free up context"), ("/init", "Write ARADHYA.md for this project"),
    ("/mode", "default · accept-edits · yolo"), ("/model", "Show or switch the model"),
    ("/resume", "Pick up an earlier session here"), ("/todos", "Show her task list"),
    ("/status", "Model, folder, tokens used"), ("/leo", "Switch to Leo (sharp, cold)"),
    ("/aradhya", "Switch back to Aradhya"), ("/exit", "Quit"),
]
BASH_PINK = "#F06FA8"


def make_reader(ui, agent, toolbox):
    """Claude Code-style input: ruled box, status line, / menu, @ files, shift+tab modes."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.application.current import get_app
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.styles import Style as PStyle
    except ImportError:
        return lambda: input("> ")
    from .tools import SKIP_DIRS
    from .ui import mode_label, mode_color

    HOME.mkdir(parents=True, exist_ok=True)
    state = {"ctrlc": 0.0, "help": False, "files": [], "files_at": 0.0}

    def files():
        if time.time() - state["files_at"] > 15:
            out = []
            for root, dirs, names in os.walk(toolbox.cwd):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
                rel = os.path.relpath(root, toolbox.cwd)
                for n in sorted(names):
                    out.append(n if rel == "." else os.path.join(rel, n).replace("\\", "/"))
                if len(out) > 5000:
                    break
            state["files"], state["files_at"] = out, time.time()
        return state["files"]

    class AraCompleter(Completer):
        def get_completions(self, doc, event):
            text = doc.text_before_cursor
            if text.startswith("/") and " " not in text:
                for name, desc in COMMANDS:
                    if name.startswith(text.lower()):
                        yield Completion(name, start_position=-len(text), display=name, display_meta=desc)
                return
            word = doc.get_word_before_cursor(WORD=True)
            if word.startswith("@"):
                q = word[1:].lower()
                hits = [f for f in files() if q in f.lower()]
                hits.sort(key=lambda f: (not os.path.basename(f).lower().startswith(q), len(f)))
                for f in hits[:12]:
                    yield Completion("@" + f + " ", start_position=-len(word), display=f)

    kb = KeyBindings()
    empty = Condition(lambda: not get_app().current_buffer.text)

    @kb.add("escape", "enter")
    def _(event):
        event.current_buffer.insert_text("\n")

    @kb.add("enter")
    def _(event):
        buf = event.current_buffer
        cs = buf.complete_state
        if cs and cs.current_completion:
            buf.apply_completion(cs.current_completion)
            if not buf.text.startswith("/"):
                return
        elif cs and cs.completions and buf.text.startswith("/"):
            buf.apply_completion(cs.completions[0])
        buf.validate_and_handle()

    @kb.add("s-tab")
    def _(event):
        toolbox.mode = MODES[(MODES.index(toolbox.mode) + 1) % len(MODES)]

    @kb.add("?", filter=empty)
    def _(event):
        state["help"] = not state["help"]

    @kb.add("c-c")
    def _(event):
        buf = event.current_buffer
        if buf.text:
            buf.reset()
            return
        if time.time() - state["ctrlc"] < 2:
            event.app.exit(exception=EOFError)
        state["ctrlc"] = time.time()

    def width():
        try:
            return get_app().output.get_size().columns
        except Exception:
            return 80

    def bashing():
        try:
            return get_app().current_buffer.text.startswith("!")
        except Exception:
            return False

    def message():
        c = BASH_PINK if bashing() else FAINT
        return [(f"fg:{c}", "─" * width() + "\n"), (f"fg:{BASH_PINK} bold" if bashing() else "fg:#D6D8DE", "> ")]

    def toolbar():
        w = width()
        c = BASH_PINK if bashing() else FAINT
        out = [(f"fg:{c}", "─" * w + "\n")]
        if state["help"]:
            rows = [("! for bash mode", "/ for commands", "shift+tab to change mode"),
                    ("@ for file paths", "esc to interrupt her", "alt+enter for a new line"),
                    ("ctrl+c to clear input", "ctrl+c twice to quit", "/help for everything")]
            for r in rows:
                out.append((f"fg:{MUTED}", "  " + "".join(x.ljust(28) for x in r) + "\n"))
            return out
        if time.time() - state["ctrlc"] < 2:
            left, lc = "  Press Ctrl-C again to exit", MUTED
        elif bashing():
            left, lc = "  ! for bash mode", BASH_PINK
        elif toolbox.mode != "default":
            left, lc = f"  ▸▸ {mode_label(toolbox.mode)} (shift+tab to cycle)", mode_color(toolbox.mode)
        else:
            left, lc = "  ? for shortcuts", MUTED
        who = "Leo" if agent.persona == "leo" else "Aradhya"
        used = agent.size_chars() / 600_000
        ctx = f"Context left until auto-compact: {max(0, int(100 - used * 100))}% · " if used > 0.5 else ""
        right = f"{ctx}{who} · {agent.provider.model}  "
        out.append((f"fg:{lc}", left))
        out.append(("", " " * max(1, w - len(left) - len(right))))
        out.append((f"fg:{MUTED}", right))
        return out

    style = PStyle.from_dict({
        "bottom-toolbar": "noreverse bg:default",
        "completion-menu": "bg:default",
        "completion-menu.completion": f"bg:default fg:{MUTED}",
        "completion-menu.completion.current": f"bg:default fg:{GOLD} bold",
        "completion-menu.meta.completion": f"bg:default fg:{FAINT}",
        "completion-menu.meta.completion.current": f"bg:default fg:{MUTED}",
        "scrollbar.background": "bg:default", "scrollbar.button": "bg:default",
    })
    from prompt_toolkit.layout.dimension import Dimension

    class AraSession(PromptSession):
        """Keeps the status line right under the input instead of at the bottom of the terminal."""
        def _get_default_buffer_control_height(self):
            buf = self.default_buffer
            w = max(10, width() - 2)
            lines = sum(max(1, -(-len(l) // w)) for l in (buf.text.split("\n") or [""]))
            cs = buf.complete_state
            menu = min(len(cs.completions), 12) if cs and cs.completions else 0
            h = lines + menu
            return Dimension(min=h, max=h, preferred=h)

    session = AraSession(history=FileHistory(str(HOME / "code_history")), key_bindings=kb, multiline=True,
                         completer=AraCompleter(), complete_while_typing=True, style=style,
                         reserve_space_for_menu=0, erase_when_done=True, refresh_interval=0.5)

    def read():
        state["help"] = False
        return session.prompt(message, bottom_toolbar=toolbar, prompt_continuation="  ")
    return read


# ─────────────────────────── main ───────────────────────────

def setup_console():
    """UTF-8 output everywhere, and on Windows switch on escape-code (VT) processing so colours, the input box
    and the logo image work in Windows Terminal, the old console host, VS Code and PowerShell alike."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetConsoleOutputCP(65001)
            k32.SetConsoleCP(65001)
            for std in (-11, -12):  # stdout, stderr
                h = k32.GetStdHandle(std)
                mode = ctypes.c_uint()
                if k32.GetConsoleMode(h, ctypes.byref(mode)):
                    k32.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass


def main(argv=None):
    setup_console()
    load_env()
    ap = argparse.ArgumentParser(prog="ara", description="Aradhya Code: Aradhya as a coding agent in your terminal.")
    ap.add_argument("prompt", nargs="*", help="what you want done")
    ap.add_argument("-p", "--print", action="store_true", help="answer once, print, exit")
    ap.add_argument("-c", "--continue", dest="cont", action="store_true", help="continue the last session here")
    ap.add_argument("-r", "--resume", action="store_true", help="pick a session to resume")
    ap.add_argument("--model", help="model name (default gemini-flash-latest)")
    ap.add_argument("--provider", help="gemini (default) | hermes | openai | openrouter | ollama")
    ap.add_argument("--base-url", help="OpenAI-compatible endpoint, e.g. http://localhost:8642/v1 for Hermes")
    ap.add_argument("--accept-edits", action="store_true", help="don't ask before editing files")
    ap.add_argument("--yolo", action="store_true", help="never ask (careful)")
    ap.add_argument("--leo", action="store_true", help="start in Leo mode")
    ap.add_argument("--cwd", help="work in this folder")
    ap.add_argument("--version", action="version", version=f"Aradhya Code {__version__}")
    args = ap.parse_args(argv)

    cwd = Path(args.cwd or os.getcwd()).resolve()
    persona = "leo" if args.leo else "aradhya"
    mode = "yolo" if args.yolo else "accept-edits" if args.accept_edits else "default"
    prompt = " ".join(args.prompt).strip()
    if not sys.stdin.isatty() and not prompt:
        prompt = sys.stdin.read().strip()

    ui = TerminalUI(interactive=not args.print, persona=persona)
    try:
        provider = make_provider(args.provider, args.model, args.base_url)
    except ProviderError as e:
        ui.error(str(e))
        return 1
    except ImportError:
        ui.error("Missing package. Run: pip install rich prompt_toolkit")
        return 1
    toolbox = ToolBox(cwd, ui, mode)
    agent = Agent(provider, toolbox, ui, persona)

    session_path = new_session_path()
    if args.cont or args.resume:
        sessions = list_sessions(cwd)
        if not sessions:
            ui.info("No earlier session in this folder. Starting fresh.")
        else:
            pick = sessions[0]
            if args.resume:
                pick = choose_session(ui, sessions) or sessions[0]
            session_path, data = pick
            agent.history = data.get("history", [])
            agent.persona = ui.persona = data.get("persona", persona)
            agent.tokens_in, agent.tokens_out = data.get("tokens", [0, 0])

    if args.print:
        if not prompt:
            ui.error("Give a prompt with -p.")
            return 1
        try:
            agent.run(prompt)
        except KeyboardInterrupt:
            return 130
        save_session(session_path, agent, cwd)
        return 0

    recent = [(d.get("updated", 0), d.get("title") or "(empty)") for _, d in list_sessions(cwd)]
    ui.banner(cwd, provider.model, mode, __version__, recent)
    started = time.time()
    if agent.history:
        ui.info(f"  Resumed: {next((m['text'][:70] for m in agent.history if m['role'] == 'user'), '')}\n")
    read = make_reader(ui, agent, toolbox)
    pending = prompt
    while True:
        if pending:
            text, pending = pending, ""
            ui.user(text)
        else:
            try:
                text = read().strip()
            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            if text.strip():
                ui.user(text.strip())
        if not text:
            continue
        if text.startswith("!"):
            ui.tool_start(f"Bash({text[1:].strip()})", True)
            res = toolbox.t_bash(text[1:].strip())
            ui.tool_end(res.summary, res.ok, res.display)
            agent.history.append({"role": "user", "text": f"(I ran `{text[1:].strip()}` myself. Output:)\n{res.output[:4000]}"})
            agent.history.append({"role": "assistant", "text": "Noted.", "tool_calls": []})
            continue
        if text.startswith("/"):
            r = slash(text, ui, agent, toolbox, cwd)
            if r == "exit":
                break
            if r == "clear":
                session_path = new_session_path()
            if isinstance(r, tuple) and r[0] == "resume":
                session_path = r[1]
            if isinstance(r, tuple) and r[0] == "run":
                pending = r[1]
                ui.info("  " + r[1][:60] + ("…" if len(r[1]) > 60 else ""), style=MUTED)
            continue
        try:
            agent.run(text)
        except KeyboardInterrupt:
            ui._stop_live()
            ui.console.print(f"[{RED}]  ⎿  Interrupted · What should she do instead?[/]\n")
        save_session(session_path, agent, cwd)
        if agent.size_chars() > 600_000:
            ui.info("  Context is getting big, compacting…")
            agent.compact()
    mins = int((time.time() - started) // 60)
    ui.console.print(f"[{FAINT}]  Session {mins}m · {agent.tokens_in:,} tokens in · {agent.tokens_out:,} out · "
                     f"ara -c to continue[/]")
    ui.console.print(f"[{GOLD}]  Bye da ✨[/]\n" if agent.persona == "aradhya" else f"[{RED}]  Leo out.[/]\n")
    return 0


def choose_session(ui, sessions):
    ui.console.print("[bold]Earlier sessions in this folder[/bold]")
    for i, (f, d) in enumerate(sessions[:15], 1):
        when = datetime.fromtimestamp(d.get("updated", 0)).strftime("%d %b %H:%M")
        n = sum(1 for m in d.get("history", []) if m["role"] == "user")
        ui.console.print(f"  {i:>2}. [{MUTED}]{when}[/]  {d.get('title') or '(empty)'}  [{MUTED}]{n} msgs[/]")
    try:
        ans = ui.console.input("Pick a number (Enter for the latest): ").strip()
        if ans.isdigit() and 1 <= int(ans) <= len(sessions[:15]):
            return sessions[int(ans) - 1]
    except (EOFError, KeyboardInterrupt):
        pass
    return None


def slash(text, ui, agent, toolbox, cwd):
    cmd, _, arg = text[1:].partition(" ")
    cmd, arg = cmd.lower(), arg.strip()
    c = ui.console
    if cmd in ("exit", "quit", "q"):
        return "exit"
    if cmd in ("help", "?"):
        c.print(HELP)
    elif cmd == "clear":
        agent.history.clear()
        toolbox.todos = []
        c.print(f"[{MUTED}]  Fresh start.[/]\n")
        return "clear"
    elif cmd == "compact":
        c.print(f"[{MUTED}]  Compacting…[/]")
        ok = agent.compact()
        c.print(f"[{MUTED}]  {'Done. Context summarized.' if ok else 'Nothing to compact.'}[/]\n")
    elif cmd == "init":
        return ("run", INIT_PROMPT)
    elif cmd == "mode":
        if arg in MODES:
            toolbox.mode = arg
        elif not arg:
            toolbox.mode = MODES[(MODES.index(toolbox.mode) + 1) % len(MODES)]
        else:
            c.print(f"[{RED}]  Modes: {', '.join(MODES)}[/]")
        c.print(f"[{MUTED}]  Mode: [/][bold]{toolbox.mode}[/]\n")
    elif cmd == "model":
        if arg:
            agent.provider.model = arg
        c.print(f"[{MUTED}]  Model: [/][bold]{agent.provider.model}[/] [{MUTED}]({agent.provider.name})[/]\n")
    elif cmd in ("leo", "aradhya"):
        agent.persona = ui.persona = cmd
        c.print(f"[{RED}]  🔴 Leo online.[/]\n" if cmd == "leo" else f"[{GOLD}]  💫 Hey kanna, I'm back ✨[/]\n")
    elif cmd == "resume":
        s = list_sessions(cwd)
        if not s:
            c.print(f"[{MUTED}]  No earlier sessions here.[/]\n")
        else:
            pick = choose_session(ui, s)
            if pick:
                agent.history = pick[1].get("history", [])
                c.print(f"[{MUTED}]  Resumed.[/]\n")
                return ("resume", pick[0])
    elif cmd == "todos":
        if toolbox.todos:
            ui.show_todos(toolbox.todos)
        else:
            c.print(f"[{MUTED}]  No todos.[/]")
        c.print()
    elif cmd == "status":
        c.print(f"  Folder   {toolbox.cwd}\n  Model    {agent.provider.model} ({agent.provider.name})\n"
                f"  Mode     {toolbox.mode}\n  Persona  {agent.persona}\n"
                f"  Tokens   {agent.tokens_in:,} in · {agent.tokens_out:,} out\n"
                f"  Context  ~{agent.size_chars() // 4:,} tokens in this conversation\n")
    else:
        c.print(f"[{RED}]  Unknown command /{cmd}. Try /help.[/]\n")
    return None


if __name__ == "__main__":
    sys.exit(main())
