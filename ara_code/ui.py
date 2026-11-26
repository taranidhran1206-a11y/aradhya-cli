"""Terminal UI for Aradhya Code, styled after Claude Code."""
import os
import random
import signal
import sys
import threading
import time
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Heading, Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from .logo import LOGO

GOLD = "#E8B55B"
GOLD_HI = "#FFE3A3"
BLUE = "#4BA3F5"
RED = "#E5534B"
GREEN = "#4EBA65"
MUTED = "#8A8F98"
FAINT = "#5C6170"
USER_BG = "#2A2D35"
ADD_BG = "#1E3B26"
DEL_BG = "#4A1F1F"
ADD_FG = "#B7F0C3"
DEL_FG = "#F5B5B5"

THEME = Theme({
    "markdown.code": f"bold {BLUE}",
    "markdown.code_block": "none",
    "markdown.item.bullet": GOLD,
    "markdown.item.number": GOLD,
    "markdown.link": BLUE,
    "markdown.link_url": f"underline {BLUE}",
    "markdown.block_quote": MUTED,
    "markdown.hr": FAINT,
    "markdown.h1": "bold",
    "markdown.h2": "bold",
    "markdown.h3": "bold",
})

VERBS = ["Thinking", "Kindling", "Brewing", "Weaving", "Untangling", "Conjuring", "Sharpening", "Plotting",
         "Igniting", "Pondering", "Crafting", "Tinkering", "Summoning", "Polishing", "Wrangling", "Musing"]
SPIN = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"]
HOLD = "\u2800"  # blank braille cell: keeps space for the logo image


class LeftHeading(Heading):
    """Headings as plain bold lines (rich boxes/centres them by default)."""
    def __rich_console__(self, console, options):
        self.text.justify = "left"
        self.text.stylize("bold")
        if self.tag == "h1":
            self.text.stylize(GOLD)
        yield self.text


class MD(Markdown):
    elements = {**Markdown.elements, "heading_open": LeftHeading}


def md(text):
    return MD(text, code_theme="monokai", hyperlinks=True)


def logo_size(size):
    """The biggest block-art logo that fits in `size` columns (0 if even the smallest doesn't)."""
    fits = [k for k in LOGO if k <= size]
    return max(fits) if fits else 0


def logo_text(size):
    out = []
    for row in LOGO[logo_size(size)]:
        t = Text()
        for i in range(0, len(row), 12):
            top, bot = row[i:i + 6], row[i + 6:i + 12]
            if top == "------" and bot == "------":
                t.append(" ")
            elif top != "------" and bot != "------":
                t.append("▀", style=Style(color="#" + top, bgcolor="#" + bot))
            elif top != "------":
                t.append("▀", style="#" + top)
            else:
                t.append("▄", style="#" + bot)
        out.append(t)
    return out


def short_path(p):
    p = str(p)
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p


def ago(ts):
    s = max(0, time.time() - ts)
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return f"{int(s // 86400)}d ago"


def fmt_tokens(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


# ─────────────────────────── spinner ───────────────────────────

class Thinking:
    """'✻ Kindling… (12s · ↓ 1.2k tokens · esc to interrupt)' with a shimmer across the word."""

    def __init__(self, accent):
        self.verb = random.choice(VERBS)
        self.start = time.time()
        self.chars = 0
        self.accent = accent

    def __rich_console__(self, console, options):
        t = time.time() - self.start
        frame = SPIN[int(t * 8) % len(SPIN)]
        word = self.verb + "…"
        pos = (t * 9) % (len(word) + 8) - 4
        line = Text()
        line.append(frame + " ", style=self.accent)
        for i, ch in enumerate(word):
            line.append(ch, style=GOLD_HI if abs(i - pos) < 1.6 else self.accent)
        bits = [f"{int(t)}s"]
        if self.chars:
            bits.append(f"↓ {fmt_tokens(self.chars // 4)} tokens")
        bits.append("esc to interrupt")
        line.append(" (" + " · ".join(bits) + ")", style=MUTED)
        yield line


# ─────────────────────────── esc to interrupt ───────────────────────────

class EscWatcher:
    """While she works, a lone Esc key interrupts (same as Ctrl+C)."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self._old = None

    def start(self):
        if self._thread or not sys.stdin.isatty():
            return
        self._stop.clear()
        if os.name == "nt":
            self._thread = threading.Thread(target=self._win, daemon=True)
        else:
            import termios
            import tty
            try:
                fd = sys.stdin.fileno()
                self._old = termios.tcgetattr(fd)
                tty.setcbreak(fd)
            except Exception:
                return
            self._thread = threading.Thread(target=self._posix, daemon=True)
        self._thread.start()

    def stop(self):
        if not self._thread:
            return
        self._stop.set()
        self._thread.join(timeout=0.5)
        self._thread = None
        if self._old is not None:
            import termios
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old)
            except Exception:
                pass
            self._old = None

    def _posix(self):
        import select
        fd = sys.stdin.fileno()
        while not self._stop.is_set():
            r, _, _ = select.select([fd], [], [], 0.1)
            if not r:
                continue
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                r2, _, _ = select.select([fd], [], [], 0.05)
                if r2:
                    os.read(fd, 16)  # arrow key or similar: ignore
                    continue
                os.kill(os.getpid(), signal.SIGINT)
                return

    def _win(self):
        import msvcrt
        while not self._stop.is_set():
            if msvcrt.kbhit() and msvcrt.getwch() == "\x1b":
                os.kill(os.getpid(), signal.SIGINT)
                return
            time.sleep(0.05)


# ─────────────────────────── main UI ───────────────────────────

def _saved_name():
    try:
        from .engines import load_config
        name = load_config().get("name")
    except Exception:
        name = None
    if name:
        return name
    try:
        import getpass
        return getpass.getuser().split("\\")[-1].capitalize() or "friend"
    except Exception:
        return "friend"


class TerminalUI:
    def __init__(self, interactive=True, persona="aradhya"):
        self.console = Console(highlight=False, theme=THEME)
        self.interactive = interactive and sys.stdin.isatty() and sys.stdout.isatty()
        self.persona = persona
        self._live = None
        self._think = None
        self._tool = None
        self.esc = EscWatcher()
        self.name = os.environ.get("ARA_NAME") or _saved_name()
        self.picture = ""

    @property
    def accent(self):
        return RED if self.persona == "leo" else GOLD

    # ── welcome ──
    def banner(self, cwd, model, mode, version, recent=()):
        w = self.console.width
        title = Text.assemble((" ✦ ", self.accent), ("Aradhya Code", f"bold {self.accent}"), (f" v{version} ", MUTED))
        who = "Leo" if self.persona == "leo" else "Aradhya"
        greet = (Text("Leo online. Orders?", style=f"bold {RED}") if self.persona == "leo"
                 else Text(f"Welcome back, {self.name}!", style="bold"))
        info = Text(f"{model} · {who}\n{short_path(cwd)}", style=MUTED, justify="center")
        if w >= 104:
            size, two = 24, True
        elif w >= 84:
            size, two = 20, True
        else:
            size, two = (16 if w >= 30 else 0), False
        art, image = self._logo(size)
        if two:
            lw = max(size + 8, 32)
            left = Table.grid()
            left.add_column(justify="center", width=lw)
            left.add_row(greet)
            left.add_row("")
            for row in art:
                left.add_row(row)
            left.add_row("")
            left.add_row(info)
            grid = Table.grid(padding=(0, 2))
            grid.add_column(width=lw)
            grid.add_column(width=1)
            grid.add_column(ratio=1)
            divider = Text("\n".join(["│"] * (len(art) + 5)), style=FAINT)
            grid.add_row(left, divider, Group(*self._tips(recent)))
            body = grid
        else:
            body = Table.grid()
            body.add_column(justify="center", width=max(20, w - 6))
            body.add_row(greet)
            body.add_row("")
            for row in art:
                body.add_row(row)
            body.add_row("")
            body.add_row(info)
        panel = Panel(body, title=title, title_align="left", border_style=self.accent, box=box.ROUNDED, padding=(1, 1))
        self._print_with_logo(panel, art, image)
        if mode != "default":
            self.console.print(Text(f"  ▸▸ {mode_label(mode)}", style=mode_color(mode)))
        self.console.print()

    def _logo(self, size):
        """Her logo as rows of text, plus the picture escape code to draw over them (or "")."""
        rich_color = self.console.color_system in ("truecolor", "256")
        if not rich_color:  # 16-colour or no-colour terminal: the picture would be mush, use a wordmark
            size = 0
        size = logo_size(size)
        from . import logo_img
        kind = logo_img.detect() if rich_color else "blocks"
        image = logo_img.render(kind, size, size // 2) if size and kind not in ("blocks", "off") else ""
        if image:  # reserve the spot (blank braille cells), the real picture is drawn over it after printing
            return [Text(HOLD * size) for _ in range(size // 2)], image
        if kind == "off":
            return [], ""
        return (logo_text(size) if size else [Text("✦  A R A D H Y A  ✦", style=f"bold {self.accent}")]), ""

    def _print_with_logo(self, panel, art, image):
        if image:
            try:
                rows = os.get_terminal_size().lines
                height = len(self.console.render_lines(panel, self.console.options, pad=False))
            except (OSError, ValueError):
                rows, height = 0, 0
            if not rows or height >= rows - 1:  # it would scroll off the top before she's drawn: use block art
                for t, row in zip(art, logo_text(len(art) * 2)):
                    t.plain = ""
                    t.append_text(row)
                image = ""
        self.picture = ""
        if image:
            spot = self._find_spot(panel)
            if not spot:  # couldn't find where she goes: block art rather than a blank gap
                for t, row in zip(art, logo_text(len(art) * 2)):
                    t.plain = ""
                    t.append_text(row)
                self.console.print(panel)
                return
            for t in art:  # print plain spaces: marker glyphs would show through her transparent parts
                t.plain = " " * len(t.plain)
            self.console.print(panel)
            self.picture = "yes"
            if spot:
                up, col = spot
                self.console.file.write(f"\x1b7\x1b[{up}A\x1b[{col + 1}G{image}\x1b8")
                self.console.file.flush()
        else:
            self.console.print(panel)

    def show_picture(self, size=12):
        """Draw just her picture, indented, for the 'can you see me?' check. True if a picture was drawn."""
        art, image = self._logo(size)
        if not image:
            return False
        grid = Table.grid()
        grid.add_column(width=4)
        grid.add_column()
        grid.add_row("", Group(*art))
        self._print_with_logo(grid, art, image)
        return bool(self.picture)

    def setup_card(self, heading, lines, title="setup"):
        """The card at the top of setup: her logo on the left, a few lines from her on the right."""
        w = self.console.width
        size = 16 if w >= 70 else 12 if w >= 44 else 0
        head = Text.assemble((" ✦ ", self.accent), ("Aradhya Code", f"bold {self.accent}"), (f" · {title} ", MUTED))
        words = [Text(heading, style="bold"), Text("")] + [Text(l, style=MUTED) if isinstance(l, str) else l
                                                           for l in lines]
        if size:
            art, image = self._logo(size)
            grid = Table.grid(padding=(0, 3))
            grid.add_column(width=size)
            grid.add_column(ratio=1)
            pad = max(0, (len(art) - len(words)) // 2)
            right = Group(*([Text("")] * pad + words))
            grid.add_row(Group(*art), right)
            panel = Panel(grid, title=head, title_align="left", border_style=self.accent, box=box.ROUNDED,
                          padding=(1, 2))
            self._print_with_logo(panel, art, image)
        else:
            self.console.print(Panel(Group(*words), title=head, title_align="left", border_style=self.accent,
                                     box=box.ROUNDED, padding=(1, 2)))

    def _find_spot(self, panel):
        """Where the reserved cells are: (lines up from the end of the card, column)."""
        from rich.cells import cell_len
        try:
            lines = self.console.render_lines(panel, self.console.options, pad=False)
        except Exception:
            return None
        for row, segs in enumerate(lines):
            col = 0
            for seg in segs:
                i = seg.text.find(HOLD)
                if i >= 0:
                    col += cell_len(seg.text[:i])
                    return len(lines) - row, col
                col += cell_len(seg.text)

    def _tips(self, recent):
        out = [Text("Tips for getting started", style=f"bold {self.accent}")]
        for tip in ["Run /init to write an ARADHYA.md so she knows this project",
                    "Ask her to fix a bug, add a feature, or explain code",
                    "Point at files with @, run shell commands with !",
                    "Shift+Tab changes how often she asks first"]:
            out.append(Text(tip))
        out.append(Text(""))
        out.append(Text("Recent activity", style=f"bold {self.accent}"))
        if recent:
            for ts, title in list(recent)[:4]:
                t = Text(no_wrap=True, overflow="ellipsis")
                t.append(f"{ago(ts):<9}", style=MUTED)
                t.append(title)
                out.append(t)
            out.append(Text("/resume for more", style=MUTED))
        else:
            out.append(Text("No recent activity", style=MUTED))
        return out

    # ── misc output ──
    def info(self, msg, style=MUTED):
        self.console.print(Text(msg, style=style))

    def error(self, msg):
        self._stop_live()
        lines = msg.splitlines() or [""]
        t = Text("  ⎿  ", style=MUTED) + Text(lines[0], style=RED)
        for l in lines[1:]:
            t.append("\n     " + l, style=MUTED)
        self.console.print(t)
        self.console.print()

    def user(self, text):
        w = self.console.width
        for i, line in enumerate(text.splitlines() or [""]):
            t = Text(("> " if i == 0 else "  ") + line, style=Style(color="#D6D8DE", bgcolor=USER_BG))
            t.pad_right(max(0, w - len(t.plain)))
            self.console.print(t)
        self.console.print()

    def _bullet(self, renderable, dot="white"):
        g = Table.grid(padding=0)
        g.add_column(width=2, no_wrap=True)
        g.add_column()
        g.add_row(Text("● ", style=dot), renderable)
        return g

    def _stop_live(self):
        if self._live is not None:
            self._live.stop()
            self._live = None
        self.esc.stop()

    # ── assistant streaming ──
    def assistant_start(self):
        self._think = Thinking(self.accent)
        if self.interactive:
            self._live = Live(self._think, console=self.console, refresh_per_second=15, transient=True,
                              vertical_overflow="visible")
            self._live.start()
            self.esc.start()

    def assistant_delta(self, text):
        if self._think:
            self._think.chars = len(text)
        if self._live is not None:
            self._live.update(Group(self._bullet(md(text)), Text(""), self._think))

    def assistant_end(self, text):
        self._stop_live()
        if text.strip():
            self.console.print(self._bullet(md(text.strip())))
            self.console.print()

    # ── tools ──
    def tool_start(self, label, read_only):
        self._tool = label
        if self.interactive:
            self._think = Thinking(self.accent)
            self._think.verb = "Running" if label.startswith("Bash") else "Working"
            self._live = Live(Group(self._head(label, FAINT), self._think), console=self.console,
                              refresh_per_second=15, transient=True)
            self._live.start()
            self.esc.start()

    def helper_step(self, label):
        """A helper agent's current step, shown under the running Helper(...) line."""
        if not self.interactive:
            return
        if self._think is None:
            self._think = Thinking(self.accent)
            self._think.verb = "Working"
        group = Group(self._head(self._tool or "Helper", FAINT), Text("  ⎿  " + label, style=MUTED), self._think)
        if self._live is None:
            self._live = Live(group, console=self.console, refresh_per_second=15, transient=True)
            self._live.start()
        else:
            self._live.update(group)

    def _head(self, label, dot):
        name, _, rest = label.partition("(")
        t = Text("● ", style=dot)
        t.append(name, style="bold")
        if rest:
            t.append("(" + rest)
        return t

    def tool_end(self, summary, ok, display=None):
        self._stop_live()
        display = display or {}
        self.console.print(self._head(self._tool or "", GREEN if ok else RED))
        body = []
        if "todos" in display:
            body.append(self._todos(display["todos"]))
        elif "diff" in display and ok:
            body.append(Text(summary, style=MUTED))
            body.append(render_diff(display["diff"], self.console.width - 8))
        elif "new" in display and ok:
            body.append(Text(summary, style=MUTED))
            body.append(render_new(display["new"], self.console.width - 8))
        elif "output" in display:
            body.append(render_output(display["output"], ok, display.get("code", 0)))
        elif summary:
            body.append(Text(summary, style=MUTED if ok else RED))
        if body:
            g = Table.grid(padding=0)
            g.add_column(width=5, no_wrap=True)
            g.add_column()
            g.add_row(Text("  ⎿  ", style=MUTED), Group(*body))
            self.console.print(g)
        self.console.print()
        self._tool = None

    def _todos(self, todos):
        t = Text()
        for i, td in enumerate(todos):
            if i:
                t.append("\n")
            st = td["status"]
            if st == "completed":
                t.append("☒ ", style=GREEN)
                t.append(td["content"], style=f"strike {MUTED}")
            elif st == "in_progress":
                t.append("◐ ", style=self.accent)
                t.append(td["content"], style=f"bold {self.accent}")
            else:
                t.append("☐ ", style=MUTED)
                t.append(td["content"])
        return t

    def show_todos(self, todos):
        self.console.print(Padding(self._todos(todos), (0, 0, 0, 2)))

    # ── permissions ──
    def ask_permission(self, title, preview, tool, cmd_prefix):
        self._stop_live()
        kind = preview.get("kind")
        text = preview.get("text", "")
        path = preview.get("path", "")
        if kind == "diff":
            inner = Panel(Group(Text(path, style="bold"), render_diff(text, self.console.width - 12, clip=60)),
                          box=box.ROUNDED, border_style=FAINT, padding=(0, 1))
            question, heading = f"Do you want to make this edit to {Path(path).name}?", "Edit file"
        elif kind == "new":
            inner = Panel(Group(Text(path, style="bold"), render_new(text, self.console.width - 12, clip=30)),
                          box=box.ROUNDED, border_style=FAINT, padding=(0, 1))
            question, heading = f"Do you want to create {Path(path).name}?", "Create file"
        else:
            inner = Padding(Group(Text(text, style="bold"), Text(title, style=MUTED)), (0, 2))
            question, heading = "Do you want to proceed?", "Bash command"
        if tool in ("edit_file", "write_file"):
            always = "Yes, allow all edits during this session (shift+tab)"
        elif cmd_prefix:
            always = f"Yes, and don't ask again for {cmd_prefix} commands this session"
        else:
            always = "Yes, and don't ask again this session"
        options = ["Yes", always, "No, and tell Aradhya what to do differently (esc)"]
        body = Group(Text(heading, style=f"bold {BLUE}"), Text(""), inner, Text(""), Text(question))
        panel = Panel(body, box=box.ROUNDED, border_style=BLUE, padding=(0, 1))
        if not self.interactive:
            self.console.print(panel)
            self.console.print(Text("  Not allowed without asking (use --yolo or --accept-edits).", style=RED))
            return "no", ""
        height = len(self.console.render_lines(panel, self.console.options, pad=False))
        self.console.print(panel)
        idx = select_option(options)
        # Like Claude Code: the question disappears once answered; the result shows below.
        self.console.file.write(f"\x1b[{height}A\x1b[J")
        self.console.file.flush()
        if idx in (0, 1):
            return ("yes" if idx == 0 else "always"), ""
        fb = ask_line("  What should she do instead? (Enter to just stop) ")
        self.console.file.write("\x1b[1A\x1b[J")
        self.console.file.flush()
        return "no", fb


def mode_label(mode):
    return {"accept-edits": "accept edits on", "yolo": "yolo on · never asks", "default": ""}[mode]


def mode_color(mode):
    return {"accept-edits": "#B48EF0", "yolo": RED, "default": MUTED}[mode]


# ─────────────────────────── renderers ───────────────────────────

def render_diff(diff, width, clip=40):
    """Unified diff → numbered lines with red/green backgrounds, like Claude Code."""
    import re
    rows = []
    old_n = new_n = 0
    for line in diff.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line)
        if m:
            if rows:
                rows.append(Text("   ⋮", style=FAINT))
            old_n, new_n = int(m.group(1)), int(m.group(2))
            continue
        body = line[1:] if line else ""
        if line.startswith("-"):
            t = Text(f"{old_n:>4} - {body}", style=Style(color=DEL_FG, bgcolor=DEL_BG))
            t.pad_right(max(0, width - len(t.plain)))
            old_n += 1
        elif line.startswith("+"):
            t = Text(f"{new_n:>4} + {body}", style=Style(color=ADD_FG, bgcolor=ADD_BG))
            t.pad_right(max(0, width - len(t.plain)))
            new_n += 1
        else:
            t = Text(f"{new_n:>4}   {body}", style=MUTED)
            old_n += 1
            new_n += 1
        t.no_wrap = True
        t.overflow = "ellipsis"
        rows.append(t)
    if len(rows) > clip:
        more = len(rows) - clip
        rows = rows[:clip] + [Text(f"   … +{more} lines", style=FAINT)]
    return Group(*rows) if rows else Text("(no changes)", style=MUTED)


def render_new(content, width, clip=12):
    lines = content.splitlines()
    rows = []
    for i, l in enumerate(lines[:clip], 1):
        r = Text(f"{i:>4} + {l}", style=Style(color=ADD_FG, bgcolor=ADD_BG), no_wrap=True, overflow="ellipsis")
        r.pad_right(max(0, width - len(r.plain)))
        rows.append(r)
    if len(lines) > clip:
        rows.append(Text(f"   … +{len(lines) - clip} lines", style=FAINT))
    return Group(*rows)


def render_output(text, ok, code):
    lines = text.splitlines() or ["(no output)"]
    t = Text("\n".join(lines[:6]), style="" if ok else RED)
    if len(lines) > 6:
        t.append(f"\n… +{len(lines) - 6} lines", style=FAINT)
    if code:
        t.append(f"\nexit code {code}", style=RED)
    return t


# ─────────────────────────── small interactive widgets ───────────────────────────

def select_option(options):
    """Arrow-key picker (↑/↓, 1-3, Enter, Esc). Returns the index; Esc picks the last option."""
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
    except ImportError:
        while True:
            for i, o in enumerate(options, 1):
                print(f"  {i}. {o}")
            a = input("❯ ").strip()
            if a.isdigit() and 1 <= int(a) <= len(options):
                return int(a) - 1
    state = {"i": 0}
    kb = KeyBindings()

    @kb.add("up")
    def _(e): state["i"] = (state["i"] - 1) % len(options)

    @kb.add("down")
    @kb.add("tab")
    def _(e): state["i"] = (state["i"] + 1) % len(options)

    @kb.add("enter")
    def _(e): e.app.exit(result=state["i"])

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _(e): e.app.exit(result=len(options) - 1)

    @kb.add("s-tab")
    def _(e): e.app.exit(result=1)

    for n in range(len(options)):
        @kb.add(str(n + 1))
        def _(e, n=n): e.app.exit(result=n)

    def text():
        out = []
        for i, o in enumerate(options):
            if i == state["i"]:
                out.append((f"fg:{BLUE} bold", f" ❯ {i + 1}. {o}\n"))
            else:
                out.append(("", f"   {i + 1}. {o}\n"))
        return out

    app = Application(layout=Layout(Window(FormattedTextControl(text), height=len(options))),
                      key_bindings=kb, erase_when_done=True)
    return app.run()


def ask_line(msg):
    try:
        from prompt_toolkit import prompt
    except ImportError:
        return input(msg).strip()
    try:
        return prompt(msg).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
