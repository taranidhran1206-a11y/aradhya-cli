"""Tools Aradhya Code can use, with permission checks for anything that changes your machine."""
import difflib
import fnmatch
import html
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

MAX_OUTPUT = 30000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", ".gradle",
             ".idea", ".next", "target", ".mypy_cache", ".pytest_cache"}
SAFE_COMMANDS = {"ls", "pwd", "cat", "head", "tail", "wc", "echo", "which", "whoami", "date", "grep", "rg",
                 "find", "tree", "file", "stat", "du", "df", "uname", "env", "printenv", "diff", "sort", "uniq"}
SAFE_GIT = {"status", "diff", "log", "show", "branch", "remote", "rev-parse", "blame", "ls-files"}

TOOLS = [
    {"name": "read_file",
     "description": "Read a text file. Returns lines with line numbers. Use offset/limit for big files. "
                    "Always read a file before editing it.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "File path (relative to the working directory or absolute)"},
         "offset": {"type": "integer", "description": "1-based line to start from"},
         "limit": {"type": "integer", "description": "Max lines to return (default 2000)"}},
         "required": ["path"]}},
    {"name": "write_file",
     "description": "Create a file or replace its whole content. Prefer edit_file for changes to existing files.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file",
     "description": "Replace an exact piece of text in a file. old_string must match exactly (including "
                    "indentation) and be unique unless replace_all is true.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
         "replace_all": {"type": "boolean"}}, "required": ["path", "old_string", "new_string"]}},
    {"name": "list_files",
     "description": "Find files by glob pattern, e.g. '**/*.py' or 'src/*.java'. Newest first.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "path": {"type": "string", "description": "Folder to search (default: working dir)"}},
         "required": ["pattern"]}},
    {"name": "grep",
     "description": "Search file contents with a regular expression. Returns file:line: text.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "path": {"type": "string"},
         "glob": {"type": "string", "description": "Only files matching this glob, e.g. '*.py'"},
         "ignore_case": {"type": "boolean"}}, "required": ["pattern"]}},
    {"name": "bash",
     "description": "Run a shell command in the working directory (bash on Linux/macOS/Termux, PowerShell on "
                    "Windows). Use for builds, tests, git, installing packages. `cd` persists between calls.",
     "parameters": {"type": "object", "properties": {
         "command": {"type": "string"},
         "timeout": {"type": "integer", "description": "Seconds (default 120, max 600)"},
         "description": {"type": "string", "description": "5-10 words on what it does"}},
         "required": ["command"]}},
    {"name": "web_fetch",
     "description": "Fetch a web page or raw file over HTTP(S) and return its text.",
     "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "todo_write",
     "description": "Keep a visible task list for multi-step work. Send the FULL list each time. "
                    "status: pending | in_progress | completed. Only one in_progress at a time.",
     "parameters": {"type": "object", "properties": {"todos": {"type": "array", "items": {
         "type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string"}},
         "required": ["content", "status"]}}}, "required": ["todos"]}},
]

LEARNING_TOOLS = [
    {"name": "memory",
     "description": "Save lasting facts that matter in EVERY future session. target 'user': who the user is, how "
                    "they like to work, their preferences and corrections. target 'memory': your own notes about "
                    "their setup, conventions, tool quirks and lessons. One short line per entry. Make all "
                    "changes to one target in one call; if it's full, remove or shorten stale entries in that same "
                    "call. Never save secrets, task progress or things that are easy to look up again. Step-by-step "
                    "procedures belong in a skill, not here.",
     "parameters": {"type": "object", "properties": {
         "target": {"type": "string", "enum": ["user", "memory"]},
         "operations": {"type": "array", "items": {"type": "object", "properties": {
             "action": {"type": "string", "enum": ["add", "patch", "remove"]},
             "content": {"type": "string", "description": "add: the new entry. patch: the text replacing old_text."},
             "old_text": {"type": "string", "description": "patch/remove: some text from the entry to change"}},
             "required": ["action"]}}},
         "required": ["target", "operations"]}},
    {"name": "skill_view",
     "description": "Load a skill (a saved playbook) by name and follow it. Returns its SKILL.md and a list of "
                    "its extra files; pass file_path to read one of those.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "file_path": {"type": "string", "description": "e.g. references/api.md"}},
         "required": ["name"]}},
    {"name": "skill_manage",
     "description": "Create or improve skills: your playbooks for recurring jobs. action 'create' needs content: a "
                    "full SKILL.md starting with frontmatter (---, name: <the name>, description: one sentence "
                    "under 160 characters starting 'Use when', ---) then the steps, exact commands, pitfalls and "
                    "how to check it worked. 'patch' fixes part of a skill (old_string -> new_string; or content "
                    "to rewrite it all). 'write_file' adds a supporting file (file_path like references/x.md, "
                    "file_content). 'delete' removes one. Write lessons, not a log of this session. scope "
                    "'project' saves it in this project only (default 'user': everywhere).",
     "parameters": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["create", "patch", "write_file", "delete"]},
         "name": {"type": "string", "description": "lowercase-with-hyphens"},
         "content": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
         "replace_all": {"type": "boolean"}, "file_path": {"type": "string"}, "file_content": {"type": "string"},
         "scope": {"type": "string", "enum": ["user", "project"]}},
         "required": ["action", "name"]}},
    {"name": "session_search",
     "description": "Search your earlier conversations with the user (all folders) for words, e.g. when they say "
                    "'like last time' or ask what you did before. Returns matching sessions with snippets.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}, "limit": {"type": "integer", "description": "default 5"}},
         "required": ["query"]}},
    {"name": "delegate",
     "description": "Hand a self-contained side task to a helper agent that starts with an empty context: a deep "
                    "search through a big codebase, research, reviewing a diff, tracking down a bug's cause. It "
                    "can read, search, run commands and edit files with the same permissions as you, but it can't "
                    "see this conversation, so put everything it needs in task and context. You get its report "
                    "back; check its claims before relying on them. Don't delegate small things.",
     "parameters": {"type": "object", "properties": {
         "task": {"type": "string", "description": "What to do and what to report back"},
         "context": {"type": "string", "description": "Paths, findings and constraints it should know"}},
         "required": ["task"]}},
]
TOOLS = TOOLS + LEARNING_TOOLS
HELPER_TOOLS = [t for t in TOOLS if t["name"] not in ("memory", "skill_manage", "delegate", "todo_write")]

READ_ONLY = {"read_file", "list_files", "grep", "web_fetch", "todo_write", "skill_view", "session_search"}
EDIT_TOOLS = {"write_file", "edit_file"}


class TextFile:
    """A text file as she read it: its encoding, byte-order mark and line endings are kept when she writes it back,
    so editing a Windows file doesn't flip it to Unix line endings (or the other way round)."""

    BOMS = [(b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"),
            (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")]

    def __init__(self, text="", encoding="utf-8", bom=b"", eol="\n"):
        self.text, self.encoding, self.bom, self.eol = text, encoding, bom, eol

    @classmethod
    def read(cls, path):
        """Returns a TextFile with \n line endings in .text, or None if it looks binary."""
        raw = Path(path).read_bytes()
        enc, bom = None, b""
        for mark, name in cls.BOMS:
            if raw.startswith(mark):
                enc, bom = name, mark
                break
        if enc is None and len(raw) > 3 and raw[1:4:2] == b"\x00\x00" and raw[0:3:2] != b"\x00\x00":
            enc = "utf-16-le"  # UTF-16 without a mark (some PowerShell output)
        if enc is None:
            if b"\x00" in raw[:4096]:
                return None
            try:
                text = raw.decode("utf-8")
                enc = "utf-8"
            except UnicodeDecodeError:
                try:
                    text, enc = raw.decode("cp1252"), "cp1252"  # older Windows files
                except UnicodeDecodeError:
                    text, enc = raw.decode("latin-1"), "latin-1"
        else:
            text = raw[len(bom):].decode(enc, "replace")
        crlf = text.count("\r\n")
        eol = "\r\n" if crlf and crlf >= (text.count("\n") - crlf) else "\n"
        return cls(text.replace("\r\n", "\n"), enc, bom, eol)

    def write(self, path, text):
        data = text.replace("\r\n", "\n")
        if self.eol != "\n":
            data = data.replace("\n", self.eol)
        try:
            body = data.encode(self.encoding)
        except UnicodeEncodeError:  # a new character the old encoding can't hold: switch to UTF-8
            body, self.encoding, self.bom = data.encode("utf-8"), "utf-8", b""
        Path(path).write_bytes(self.bom + body)


def child_env():
    """Environment for commands she runs: UTF-8 from Python and git, whatever the system's code page."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", LESSCHARSET="utf-8")
    try:
        n = int(env.get("GIT_CONFIG_COUNT", "0") or 0)
    except ValueError:
        n = 0
    env.update({"GIT_CONFIG_COUNT": str(n + 1), f"GIT_CONFIG_KEY_{n}": "core.quotepath",
                f"GIT_CONFIG_VALUE_{n}": "off"})  # show non-English file names as they are
    return env


PS_UTF8 = ("$ProgressPreference='SilentlyContinue'; "
           "try { [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false) } catch {}; "
           "$OutputEncoding=[Text.UTF8Encoding]::new($false); ")


def decode_output(data):
    if isinstance(data, str):
        return data
    text = (data or b"").decode("utf-8", "replace")
    return text[1:] if text.startswith("\ufeff") else text


class ToolResult:
    def __init__(self, output, ok=True, summary="", stop=False, display=None):
        self.output, self.ok, self.summary, self.stop = output, ok, summary, stop
        self.display = display or {}


class ToolBox:
    """Runs tools. mode: 'default' asks before edits/commands, 'accept-edits' auto-approves file
    edits, 'yolo' never asks."""

    def __init__(self, cwd, ui, mode="default"):
        self.cwd = Path(cwd).resolve()
        self.ui = ui
        self.mode = mode
        self.read_paths = set()
        self.always = set()         # tool names approved for the session
        self.always_cmds = set()    # bash command prefixes approved for the session
        self.todos = []
        self.session_path = None    # so session_search can skip the conversation we're in
        self.delegate_fn = None     # set by the agent: runs a helper agent

    # ── helpers ──
    def _path(self, p):
        q = Path(os.path.expanduser(p))
        return (q if q.is_absolute() else self.cwd / q).resolve()

    def _rel(self, p):
        try:
            return str(Path(p).relative_to(self.cwd))
        except ValueError:
            return str(p)

    def label(self, name, args):
        """Short 'Tool(arg)' label for the transcript."""
        a = args or {}
        if name in ("read_file", "write_file", "edit_file"):
            return f"{ {'read_file': 'Read', 'write_file': 'Write', 'edit_file': 'Update'}[name]}({self._rel(self._path(a.get('path', '')))})"
        if name == "bash":
            cmd = a.get("command", "")
            return f"Bash({cmd if len(cmd) < 70 else cmd[:67] + '…'})"
        if name == "list_files":
            return f"Search({a.get('pattern', '')})"
        if name == "grep":
            return f"Grep(\"{a.get('pattern', '')}\")"
        if name == "web_fetch":
            return f"Fetch({a.get('url', '')})"
        if name == "todo_write":
            return "Update Todos"
        if name == "memory":
            return f"Remember({'about you' if a.get('target') == 'user' else 'notes'})"
        if name == "skill_view":
            return f"Skill({a.get('name', '')}{' · ' + a['file_path'] if a.get('file_path') else ''})"
        if name == "skill_manage":
            verb = {"create": "New skill", "patch": "Improve skill", "write_file": "Skill file",
                    "delete": "Delete skill"}.get(a.get("action"), "Skill")
            return f"{verb}({a.get('name', '')})"
        if name == "session_search":
            return f"Recall(\"{a.get('query', '')}\")"
        if name == "delegate":
            task = " ".join(str(a.get("task", "")).split())
            return f"Helper({task if len(task) < 60 else task[:57] + '…'})"
        return f"{name}()"

    def _permit(self, name, title, preview, cmd_prefix=None):
        if self.mode == "yolo" or name in self.always:
            return True, ""
        if name in EDIT_TOOLS and self.mode == "accept-edits":
            return True, ""
        if cmd_prefix and cmd_prefix in self.always_cmds:
            return True, ""
        choice, feedback = self.ui.ask_permission(title, preview, name, cmd_prefix)
        if choice == "always":
            if cmd_prefix:
                self.always_cmds.add(cmd_prefix)
            else:
                self.always.add(name)
            return True, ""
        return choice == "yes", feedback

    def _denied(self, feedback):
        msg = "The user rejected this action."
        if feedback:
            return ToolResult(f"{msg} Their instructions: {feedback}", ok=False, summary=f"No: {feedback}")
        return ToolResult(msg + " Stop and wait for the user to tell you what to do next.",
                          ok=False, summary="No (you said stop)", stop=True)

    # ── dispatch ──
    def run(self, name, args):
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            return ToolResult(f"Unknown tool: {name}", ok=False, summary="Unknown tool")
        try:
            return fn(**(args or {}))
        except TypeError as e:
            return ToolResult(f"Bad arguments for {name}: {e}", ok=False, summary="Bad arguments")
        except Exception as e:  # noqa: BLE001 - report every failure back to the model
            return ToolResult(f"{type(e).__name__}: {e}", ok=False, summary=f"Error: {e}")

    # ── tools ──
    def t_read_file(self, path, offset=None, limit=None):
        p = self._path(path)
        if p.is_dir():
            return ToolResult(f"{path} is a folder. Use list_files.", ok=False, summary="Is a folder")
        if not p.exists():
            return ToolResult(f"File not found: {path}", ok=False, summary="Not found")
        tf = TextFile.read(p)
        if tf is None:
            return ToolResult(f"{path} looks binary ({p.stat().st_size} bytes).", ok=False, summary="Binary file")
        lines = tf.text.splitlines()
        start = max(1, int(offset or 1))
        n = int(limit or 2000)
        chunk = lines[start - 1:start - 1 + n]
        self.read_paths.add(str(p))
        body = "\n".join(f"{i:>6}\t{l[:2000]}" for i, l in enumerate(chunk, start))
        more = f"\n… {len(lines) - (start - 1 + n)} more lines (use offset)" if start - 1 + n < len(lines) else ""
        return ToolResult(body + more if body else "(empty file)", summary=f"Read {len(chunk)} lines")

    def t_write_file(self, path, content):
        p = self._path(path)
        tf = TextFile.read(p) if p.exists() else TextFile()
        old = (tf.text if tf is not None else "") if p.exists() else None
        tf = tf or TextFile()
        content = content.replace("\r\n", "\n")
        if old is not None and str(p) not in self.read_paths:
            return ToolResult(f"{path} already exists. Read it first, then write.", ok=False,
                              summary="Read it first")
        preview = diff_text(old or "", content, self._rel(p)) if old is not None else content
        ok, fb = self._permit("write_file", ("Overwrite " if old is not None else "Create ") + self._rel(p),
                              {"kind": "diff" if old is not None else "new", "text": preview, "path": self._rel(p)})
        if not ok:
            return self._denied(fb)
        p.parent.mkdir(parents=True, exist_ok=True)
        tf.write(p, content)
        self.read_paths.add(str(p))
        n = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
        return ToolResult(f"Wrote {n} lines to {self._rel(p)}",
                          summary=f"Wrote {n} lines to {self._rel(p)}" if old is None else f"Rewrote {self._rel(p)} ({n} lines)",
                          display={"new": content, "path": self._rel(p)} if old is None else {"diff": preview})

    def t_edit_file(self, path, old_string, new_string, replace_all=False):
        p = self._path(path)
        if not p.exists():
            return ToolResult(f"File not found: {path}", ok=False, summary="Not found")
        if str(p) not in self.read_paths:
            return ToolResult(f"Read {path} before editing it.", ok=False, summary="Read it first")
        tf = TextFile.read(p)
        if tf is None:
            return ToolResult(f"{path} looks binary; it can't be edited as text.", ok=False, summary="Binary file")
        old = tf.text
        old_string, new_string = old_string.replace("\r\n", "\n"), new_string.replace("\r\n", "\n")
        if old_string == new_string:
            return ToolResult("old_string and new_string are the same.", ok=False, summary="No change")
        count = old.count(old_string)
        if count == 0:
            return ToolResult("old_string wasn't found. Re-read the file and copy the text exactly.", ok=False,
                              summary="Text not found")
        if count > 1 and not replace_all:
            return ToolResult(f"old_string appears {count} times. Add more surrounding lines to make it unique, "
                              "or set replace_all.", ok=False, summary=f"{count} matches")
        new = old.replace(old_string, new_string) if replace_all else old.replace(old_string, new_string, 1)
        d = diff_text(old, new, self._rel(p))
        ok, fb = self._permit("edit_file", "Edit " + self._rel(p), {"kind": "diff", "text": d, "path": self._rel(p)})
        if not ok:
            return self._denied(fb)
        tf.write(p, new)
        added = sum(1 for l in d.splitlines() if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in d.splitlines() if l.startswith("-") and not l.startswith("---"))
        return ToolResult(f"Edited {self._rel(p)}:\n{d}",
                          summary=f"Updated {self._rel(p)} with {added} addition{'s' * (added != 1)} and {removed} removal{'s' * (removed != 1)}",
                          display={"diff": d})

    def t_list_files(self, pattern, path=None):
        base = self._path(path or ".")
        hits = []
        for p in base.glob(pattern):
            if any(part in SKIP_DIRS for part in p.relative_to(base).parts):
                continue
            if p.is_file():
                hits.append(p)
            if len(hits) > 2000:
                break
        hits.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        out = "\n".join(self._rel(h) for h in hits[:300])
        more = f"\n… and {len(hits) - 300} more" if len(hits) > 300 else ""
        return ToolResult((out + more) or "No files found.", summary=f"Found {len(hits)} file{'s' * (len(hits) != 1)}")

    def t_grep(self, pattern, path=None, glob=None, ignore_case=False):
        base = self._path(path or ".")
        rg = shutil.which("rg")
        if rg:
            cmd = [rg, "-n", "--no-heading", "--max-columns", "300", "-m", "50"]
            if ignore_case:
                cmd.append("-i")
            if glob:
                cmd += ["-g", glob]
            cmd += ["-e", pattern, str(base)]
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            lines = [self._rel_line(l) for l in r.stdout.splitlines()]
        else:
            flags = re.I if ignore_case else 0
            rx = re.compile(pattern, flags)
            lines = []
            files = [base] if base.is_file() else _walk(base)
            for f in files:
                if glob and not fnmatch.fnmatch(f.name, glob):
                    continue
                try:
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        for i, line in enumerate(fh, 1):
                            if rx.search(line):
                                lines.append(f"{self._rel(f)}:{i}: {line.rstrip()[:300]}")
                except OSError:
                    continue
                if len(lines) > 500:
                    break
        out = "\n".join(lines[:500])
        files = len({l.split(":", 1)[0] for l in lines})
        return ToolResult(out or "No matches.", summary=f"Found {len(lines)} match{'es' * (len(lines) != 1)} in {files} file{'s' * (files != 1)}")

    def _rel_line(self, line):
        path, _, rest = line.partition(":")
        return self._rel(Path(path)) + ":" + rest

    def t_bash(self, command, timeout=120, description=None):
        prefix = command_prefix(command)
        if not is_safe_command(command):
            ok, fb = self._permit("bash", description or "Run a command",
                                  {"kind": "command", "text": command}, cmd_prefix=prefix)
            if not ok:
                return self._denied(fb)
        timeout = max(1, min(int(timeout or 120), 600))
        marker = "__ARA_CWD__"
        if os.name == "nt":
            args = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    f"{PS_UTF8}{command}; echo '{marker}'; (Get-Location).Path"]
        else:
            shell = shutil.which("bash") or "/bin/sh"
            args = [shell, "-c", f"{command}\n__ara_rc=$?; echo '{marker}'; pwd; exit $__ara_rc"]
        try:
            r = subprocess.run(args, cwd=self.cwd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                               env=child_env())
        except subprocess.TimeoutExpired as e:
            out = decode_output(e.stdout)
            return ToolResult(f"Timed out after {timeout}s.\n{out[-MAX_OUTPUT:]}", ok=False, summary=f"Timed out ({timeout}s)")
        stdout, stderr = decode_output(r.stdout), decode_output(r.stderr)
        if marker in stdout:
            stdout, _, tail = stdout.rpartition(marker)
            newdir = tail.strip().splitlines()[-1] if tail.strip() else ""
            if newdir and Path(newdir).is_dir():
                self.cwd = Path(newdir).resolve()
        text = stdout.replace("\r\n", "\n").rstrip()
        if stderr.strip():
            text += ("\n" if text else "") + stderr.replace("\r\n", "\n").rstrip()
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT // 2] + f"\n… [{len(text) - MAX_OUTPUT} chars cut] …\n" + text[-MAX_OUTPUT // 2:]
        code = r.returncode
        body = (text or "(no output)") + (f"\n[exit code {code}]" if code else "")
        first = next((l for l in text.splitlines() if l.strip()), "(no output)")
        summary = first[:100] + (f"  [exit {code}]" if code else "")
        return ToolResult(body, ok=code == 0, summary=summary, display={"output": text, "code": code})

    def t_web_fetch(self, url):
        if not re.match(r"^https?://", url):
            return ToolResult("URL must start with http:// or https://", ok=False, summary="Bad URL")
        req = urllib.request.Request(url, headers={"User-Agent": "AradhyaCode/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(3_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
            ctype = r.headers.get("Content-Type", "")
        if "html" in ctype:
            data = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", data)
            data = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", data)
            data = html.unescape(re.sub(r"(?s)<[^>]+>", " ", data))
            data = re.sub(r"[ \t]+", " ", data)
            data = re.sub(r"\n\s*\n+", "\n\n", data).strip()
        return ToolResult(data[:MAX_OUTPUT], summary=f"Fetched {len(data):,} chars")

    def t_todo_write(self, todos):
        self.todos = [{"content": str(t.get("content", "")), "status": str(t.get("status", "pending"))} for t in todos]
        done = sum(1 for t in self.todos if t["status"] == "completed")
        return ToolResult(f"Todo list updated ({done}/{len(self.todos)} done).", summary="",
                          display={"todos": self.todos})

    # ── remembering and learning ──
    def t_memory(self, target, operations=None, **single):
        from . import soul
        if not operations and single.get("action"):
            operations = [single]
        ok, msg, changes = soul.apply(target, operations or [])
        if not ok:
            return ToolResult(msg, ok=False, summary=msg.splitlines()[0][:120])
        if not changes:
            return ToolResult("Already saved; nothing changed.", summary="Already knew that")
        verb = {"add": "Remembered", "patch": "Updated", "remove": "Forgot"}
        shown = "; ".join(f"{verb[a]}: {t if len(t) < 90 else t[:87] + '…'}" for a, t in changes)
        return ToolResult(msg, summary=shown)

    def t_skill_view(self, name, file_path=None):
        from . import skills
        skill, text = skills.view(self.cwd, name, file_path)
        if skill is None:
            return ToolResult(text, ok=False, summary=text.split(".")[0])
        where = "this project" if skill.scope == "project" else "your skills"
        return ToolResult(text, summary=f"Loaded {skill.name}{' · ' + file_path if file_path else ''} ({where})")

    def t_skill_manage(self, action, name, content=None, old_string=None, new_string=None, replace_all=False,
                       file_path=None, file_content=None, scope="user"):
        from . import skills
        existing = skills.find(self.cwd, name)
        in_project = (scope == "project" and action == "create") or (existing is not None and existing.scope == "project")
        if action == "delete" or in_project:  # deleting, or writing inside the project: ask like any edit
            kind = "write_file" if in_project and action != "delete" else "skill_manage"
            where = str(existing.folder) if existing else f".aradhya/skills/{name}"
            ok, fb = self._permit(kind, f"{action} skill {name}",
                                  {"kind": "new", "path": where, "text": content or file_content or f"Delete {where}"})
            if not ok:
                return self._denied(fb)
        ok, msg, display = skills.manage(self.cwd, action, name, content, old_string, new_string, replace_all,
                                         file_path, file_content, scope)
        return ToolResult(msg, ok=ok, summary=msg if not ok else msg.split(" at ")[0], display=display if ok else {})

    def t_session_search(self, query, limit=5):
        from . import soul
        hits = soul.search_sessions(query, int(limit or 5), skip=self.session_path)
        if not hits:
            return ToolResult(f"No earlier conversation mentions '{query}'.", summary="Nothing found")
        out = []
        for h in hits:
            out.append(f"## {h['title']}\n{h['when']} · {h['folder']} · {h['matches']} matching messages")
            out.extend(f"> {s}" for s in h["snippets"])
        return ToolResult("\n".join(out), summary=f"{len(hits)} earlier session{'s' * (len(hits) != 1)}")

    def t_delegate(self, task, context=None):
        if not self.delegate_fn:
            return ToolResult("A helper can't start a helper of its own. Do it yourself.", ok=False,
                              summary="Not available here")
        report, steps = self.delegate_fn(task, context)
        return ToolResult(report or "(The helper finished without a report.)",
                          summary=f"Helper finished in {steps} step{'s' * (steps != 1)}")


def _walk(base):
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            yield Path(root) / f


def diff_text(old, new, name):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile="a/" + name, tofile="b/" + name, n=3))


def command_prefix(cmd):
    """'git commit -m x' -> 'git commit', 'npm run build' -> 'npm run', 'pytest -q' -> 'pytest'."""
    words = cmd.strip().split()
    if not words:
        return ""
    if words[0] in ("git", "npm", "pnpm", "yarn", "cargo", "go", "docker", "pip", "pip3", "uv", "systemctl",
                    "gradle", "./gradlew", "python", "python3", "kubectl") and len(words) > 1:
        return " ".join(words[:2])
    return words[0]


def is_safe_command(cmd):
    """Read-only commands that never need asking."""
    if re.search(r"[>`]|\$\(|\brm\b|\bsudo\b|\bmv\b|\bcp\b|\bchmod\b|\btee\b|-delete\b|-exec\b", cmd):
        return False
    for seg in re.split(r"&&|\|\||;|\|", cmd):
        w = seg.strip().split()
        if not w:
            continue
        if w[0] == "cd":
            continue
        if w[0] == "git" and len(w) > 1 and w[1] in SAFE_GIT:
            continue
        if w[0] in SAFE_COMMANDS:
            continue
        return False
    return True
