"""The agent loop: ask the model, run the tools it calls, feed results back, repeat."""
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path

from . import skills, soul
from .providers import ProviderError
from .tools import HELPER_TOOLS, TOOLS, READ_ONLY

MAX_STEPS = 60

RULES = """
# How you work
- You act on the user's machine through tools. Do the work yourself; don't tell the user to run things you can run.
- Explore before changing: use list_files/grep/read_file to understand the code. Read a file before editing it.
- Prefer edit_file for small, exact changes. Match the existing style. Don't add comments explaining the obvious.
- After changing code, verify: run the tests, the build, or the script. Fix what you broke.
- For work with 3+ steps, keep a todo list with todo_write and update it as you go.
- Never commit, push, delete branches or deploy unless the user asked. Never print secrets from .env files.
- If an action is rejected, stop and wait unless the user said what to do instead.
- If the request is unclear and a wrong guess would be costly, ask one short question.

# How you talk
- This is a terminal. Be concise: a short sentence before tool calls when useful, and a brief summary at the end.
- Markdown is rendered. Use `code` for paths and commands. Reference code as `path:line`.
- When the user writes @some/path they are pointing at that file or folder: read it.
- No preamble like "Great question". No recap of every step at the end.
"""


def git_info(cwd):
    try:
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, capture_output=True,
                                text=True, timeout=5).stdout.strip()
        if not branch:
            return "not a git repo"
        status = subprocess.run(["git", "status", "--short"], cwd=cwd, capture_output=True, text=True,
                                timeout=5).stdout.strip().splitlines()
        return f"branch {branch}, {len(status)} changed file{'s' * (len(status) != 1)}"
    except Exception:
        return "not a git repo"


def project_memory(cwd):
    """ARADHYA.md files: ~/.aradhya/ARADHYA.md, then every folder from the git root (or /) down to cwd.
    AGENTS.md and CLAUDE.md are read too so existing projects just work."""
    found = []
    home = Path.home() / ".aradhya" / "ARADHYA.md"
    if home.exists():
        found.append(home)
    cwd = Path(cwd).resolve()
    chain = [cwd] + list(cwd.parents)
    root_idx = next((i for i, p in enumerate(chain) if (p / ".git").exists()), len(chain) - 1)
    for folder in reversed(chain[:root_idx + 1]):
        for name in ("ARADHYA.md", "AGENTS.md", "CLAUDE.md"):
            f = folder / name
            if f.exists():
                found.append(f)
                break
    parts = []
    for f in found:
        try:
            parts.append(f"## From {f}\n{f.read_text('utf-8', 'replace')[:20000]}")
        except OSError:
            pass
    return parts


LEARNING = """
# Remembering and getting better
- Skills are playbooks you or the user saved for recurring jobs. Before starting a task, scan the skills list below.
  If one matches even partly, load it with skill_view and follow it: it holds the user's preferred way and the
  pitfalls already found.
- If a skill you used had wrong or missing steps, fix it with skill_manage (patch) before you finish.
- After a hard or many-step task, a tricky fix, or when the user corrects how you do something, save the approach
  as a skill (skill_manage create) or improve the one you used. Say so in one line. Don't make skills for one-offs.
- memory is for short facts that matter in every session: who {name} is and how they like to work (target 'user'),
  and their setup and conventions (target 'memory'). Save them when you learn them, without being asked.
- session_search finds earlier conversations. delegate hands a big self-contained side task to a helper.
"""

HELPER = """
# You are a helper
The main Aradhya handed you one task. You can't see her conversation with {name}; everything you know is below.
Work it through with your tools, then reply with a short report: what you found or changed (with file paths and
line numbers), how you checked it, and anything left open. No questions back; if something is unclear, make the
safest reasonable choice and say which.
"""


def build_system(cwd, persona="aradhya", name=None, helper=False):
    name = name or "the user"
    mem = project_memory(cwd)
    env = (f"\n# Environment\n- Working directory: {cwd}\n- Platform: {platform.system()} {platform.release()}"
           f" ({'PowerShell' if os.name == 'nt' else 'bash'})\n- Git: {git_info(cwd)}\n"
           f"- Now: {datetime.now().strftime('%A %d %B %Y, %H:%M')}\n")
    text = soul.load_soul(persona, name) + "\n" + RULES
    text += (HELPER if helper else LEARNING).format(name=name) + env
    remembered = soul.prompt_block(name)
    if remembered:
        text += "\n# What you remember\n" + remembered + "\n"
    idx = skills.index(cwd)
    if idx and not helper:
        text += "\n# Skills\n" + idx + "\n"
    elif idx:
        text += "\n# Skills you can load with skill_view\n" + idx + "\n"
    if mem:
        text += "\n# Project instructions (follow these)\n" + "\n\n".join(mem)
    return text


class Agent:
    def __init__(self, provider, toolbox, ui, persona="aradhya", helper=False):
        self.provider = provider
        self.tools = toolbox
        self.ui = ui
        self.persona = persona
        self.helper = helper
        self.specs = HELPER_TOOLS if helper else TOOLS
        self.history = []
        self.tokens_in = 0
        self.tokens_out = 0
        self.last_steps = 0         # tool calls in the last turn (for the /learn nudge)
        self.last_learned = False   # did she save a skill in the last turn
        if not helper:
            toolbox.delegate_fn = self.delegate

    def system(self):
        return build_system(self.tools.cwd, self.persona, getattr(self.ui, "name", None), self.helper)

    def delegate(self, task, context=None):
        """Run a helper agent on a side task with a fresh context. Returns (report, steps)."""
        ui = HelperUI(self.ui)
        child = Agent(self.provider, self.tools, ui, self.persona, helper=True)
        prompt = task.strip() + (("\n\nContext:\n" + context.strip()) if context and context.strip() else "")
        saved = self.tools.delegate_fn
        self.tools.delegate_fn = None
        try:
            child.run(prompt, max_steps=30)
        finally:
            self.tools.delegate_fn = saved
            self.tokens_in += child.tokens_in
            self.tokens_out += child.tokens_out
        report = next((m["text"] for m in reversed(child.history) if m["role"] == "assistant" and m.get("text")), "")
        if ui.errors and not report:
            report = "The helper hit a problem: " + ui.errors[-1]
        return report, child.last_steps

    def run(self, user_text, max_steps=MAX_STEPS):
        """One user turn. May take many model steps. Raises KeyboardInterrupt after leaving history valid."""
        self.history.append({"role": "user", "text": user_text})
        self.last_steps, self.last_learned = 0, False
        for _ in range(max_steps):
            text, calls = "", []
            self.ui.assistant_start()
            try:
                for kind, val in self.provider.stream(self.history, self.system(), self.specs):
                    if kind == "text":
                        text += val
                        self.ui.assistant_delta(text)
                    elif kind == "tool_call":
                        calls.append(val)
                    elif kind == "usage":
                        self.tokens_in += val[0]
                        self.tokens_out += val[1]
            except KeyboardInterrupt:
                self.ui.assistant_end(text)
                self.history.append({"role": "assistant", "text": (text + "\n[interrupted by user]").strip(),
                                     "tool_calls": []})
                raise
            except ProviderError as e:
                self.ui.assistant_end(text)
                self.ui.error(str(e))
                if text:
                    self.history.append({"role": "assistant", "text": text, "tool_calls": []})
                return
            self.ui.assistant_end(text)
            self.history.append({"role": "assistant", "text": text, "tool_calls": calls})
            if not calls:
                return
            stop = False
            for i, call in enumerate(calls):
                if stop:
                    self.history.append({"role": "tool", "id": call["id"], "gid": call.get("gid"), "name": call["name"],
                                         "result": "Skipped: the user rejected an earlier action."})
                    continue
                self.last_steps += 1
                if call["name"] == "skill_manage":
                    self.last_learned = True
                self.ui.tool_start(self.tools.label(call["name"], call["args"]), call["name"] in READ_ONLY)
                try:
                    res = self.tools.run(call["name"], call["args"])
                except KeyboardInterrupt:
                    for c in calls[i:]:
                        self.history.append({"role": "tool", "id": c["id"], "gid": c.get("gid"), "name": c["name"],
                                             "result": "Interrupted by the user."})
                    self.ui.tool_end("Interrupted by user", False, {})
                    raise
                self.ui.tool_end(res.summary, res.ok, res.display)
                self.history.append({"role": "tool", "id": call["id"], "gid": call.get("gid"), "name": call["name"],
                                     "result": res.output})
                if res.stop:
                    stop = True
            if stop:
                return
        self.ui.error(f"Stopped after {max_steps} steps. Say 'continue' to keep going.")

    def compact(self):
        """Replace the conversation with a summary so long sessions keep fitting."""
        if not self.history:
            return False
        ask = ("Summarize our session so far for your own future reference: the goal, decisions, files changed "
               "(with paths), what works, what's left, and any gotchas. Be specific and brief. No tool calls.")
        saved = list(self.history)
        self.history.append({"role": "user", "text": ask})
        summary = ""
        for kind, val in self.provider.stream(self.history, self.system(), []):
            if kind == "text":
                summary += val
        if not summary.strip():
            self.history = saved
            return False
        self.history = [{"role": "user", "text": "Summary of our earlier session:\n\n" + summary.strip()},
                        {"role": "assistant", "text": "Got it. Ready to continue.", "tool_calls": []}]
        return True

    def size_chars(self):
        return sum(len(m.get("text") or "") + len(m.get("result") or "") +
                   sum(len(str(c["args"])) for c in m.get("tool_calls", [])) for m in self.history)


class HelperUI:
    """What a helper agent shows: nothing of its own, just one line of progress under the Helper(...) step."""

    def __init__(self, ui):
        self.ui = ui
        self.name = getattr(ui, "name", None)
        self.errors = []

    def assistant_start(self):
        pass

    def assistant_delta(self, text):
        pass

    def assistant_end(self, text):
        pass

    def tool_start(self, label, read_only):
        if hasattr(self.ui, "helper_step"):
            self.ui.helper_step(label)

    def tool_end(self, summary, ok, display=None):
        pass

    def error(self, msg):
        self.errors.append(str(msg))

    def info(self, *a, **k):
        pass
