"""What the terminal can do, so she looks right everywhere.

- UTF-8 in and out on every platform. On Windows the console's code pages are switched to UTF-8 while she runs
  and put back when she exits, and escape codes (colours, the input box, pictures) are turned on.
- Plain-symbol mode for consoles whose font lacks symbols like ✦ ⎿ ❯ ✓ (the classic Windows console with Consolas
  or Lucida Console, the Linux text console). Every symbol is swapped for one the font has, at the same width, so
  boxes and columns still line up. ARA_ASCII=1 forces it, ARA_ASCII=0 turns it off.
- One round trip to ask the terminal about pictures (sixel) and its character size in pixels. The question ends with
  a "device attributes" query every terminal answers, so a slow SSH link can't leave stray replies in the input box.
"""
import atexit
import os
import re
import sys
import time

# Same width in, same width out: tables and borders keep their shape.
PLAIN = {
    "✦": "♦", "✓": "√", "✗": "x", "❯": "►", "▸": "►", "⎿": "└", "◆": "♦", "↩": "←", "⋮": ":",
    "✻": "*", "✢": "+", "✳": "*", "✶": "*", "✽": "*", "☐": "□", "☒": "■", "◐": "►",
    "╭": "┌", "╮": "┐", "╰": "└", "╯": "┘", "⠀": " ",
    "✨": "* ", "💫": "* ", "🔴": "• ", "🟢": "• ", "⚠": "!",
}
PLAIN_TABLE = str.maketrans(PLAIN)
PLAIN_TABLE.update({cp: "*" for cp in range(0x2801, 0x2900)})  # braille spinner dots

GOOD_FONTS = ("cascadia", "nerd", "jetbrains", "fira", "hack", "iosevka", "dejavu", "sarasa", "meslo",
              "source code", "ubuntu mono", "roboto mono", "victor", "monaspace", "noto")

_state = {"plain": None, "probe": None}


# ─────────────────────────── plain symbols ───────────────────────────

def console_font():
    """The classic Windows console's font name, or '' if unknown."""
    if os.name != "nt":
        return ""
    try:
        import ctypes

        class COORD(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class FONTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("nFont", ctypes.c_ulong), ("dwFontSize", COORD),
                        ("FontFamily", ctypes.c_uint), ("FontWeight", ctypes.c_uint), ("FaceName", ctypes.c_wchar * 32)]

        info = FONTINFO()
        info.cbSize = ctypes.sizeof(FONTINFO)
        h = ctypes.windll.kernel32.GetStdHandle(-11)
        if ctypes.windll.kernel32.GetCurrentConsoleFontEx(h, False, ctypes.byref(info)):
            return info.FaceName or ""
    except Exception:
        pass
    return ""


def windows_terminal_app():
    """Windows Terminal, VS Code, ConEmu, WezTerm, Alacritty, mintty…: anything but the classic console window."""
    env = os.environ
    return bool(env.get("WT_SESSION") or env.get("TERM_PROGRAM") or env.get("ConEmuPID") or env.get("TERMINAL_EMULATOR")
                or env.get("ALACRITTY_WINDOW_ID") or env.get("WEZTERM_PANE"))


def plain_symbols():
    """True when the console's font can't draw the fancy symbols."""
    if _state["plain"] is not None:
        return _state["plain"]
    v = os.environ.get("ARA_ASCII", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        res = True
    elif v in ("0", "false", "no", "off"):
        res = False
    elif os.name == "nt":
        if windows_terminal_app():
            res = False
        else:  # the classic console window: depends on its font
            font = console_font().lower()
            res = not any(f in font for f in GOOD_FONTS) if font else not os.environ.get("TERM", "").startswith("xterm")
    else:
        res = os.environ.get("TERM") == "linux"  # the Linux text console
    _state["plain"] = res
    return res


def sym(text):
    """A symbol for prompt_toolkit or other text that doesn't pass through stdout."""
    return text.translate(PLAIN_TABLE) if plain_symbols() else text


class PlainStream:
    """Wraps stdout/stderr and swaps symbols the font can't draw. It deliberately has no .buffer, so prompt_toolkit
    writes through it too."""

    def __init__(self, stream):
        self._s = stream

    def write(self, text):
        return self._s.write(text.translate(PLAIN_TABLE))

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        return self._s.flush()

    def fileno(self):
        return self._s.fileno()

    def isatty(self):
        return self._s.isatty()

    @property
    def encoding(self):
        return getattr(self._s, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._s, "errors", "replace")

    @property
    def closed(self):
        return getattr(self._s, "closed", False)

    def __getattr__(self, name):
        if name == "buffer":
            raise AttributeError(name)
        return getattr(self._s, name)


# ─────────────────────────── console setup ───────────────────────────

def setup_console():
    """UTF-8 in and out; on Windows, escape codes on and UTF-8 code pages for as long as she runs."""
    if getattr(sys, "_ara_console_ready", False):
        return
    sys._ara_console_ready = True
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "").replace("_", "")
        if stream is not None and enc != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            old_out, old_in = k32.GetConsoleOutputCP(), k32.GetConsoleCP()
            k32.SetConsoleOutputCP(65001)
            k32.SetConsoleCP(65001)
            modes = []
            for std in (-11, -12):  # stdout, stderr
                h = k32.GetStdHandle(std)
                mode = ctypes.c_uint()
                if k32.GetConsoleMode(h, ctypes.byref(mode)):
                    modes.append((h, mode.value))
                    k32.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING

            def restore():
                try:
                    sys.stdout.flush()
                except Exception:
                    pass
                if old_out:
                    k32.SetConsoleOutputCP(old_out)
                if old_in:
                    k32.SetConsoleCP(old_in)
                for h, m in modes:
                    k32.SetConsoleMode(h, m)

            atexit.register(restore)
        except Exception:
            pass
    if plain_symbols():
        sys.stdout = PlainStream(sys.stdout)
        sys.stderr = PlainStream(sys.stderr)


# ─────────────────────────── asking the terminal ───────────────────────────

DA1 = re.compile(r"\x1b\[\?([\d;]*)c")


def probe():
    """Ask once: can it draw sixel pictures, and how big is a character cell in pixels?
    Returns {"sixel": bool, "cell": (w, h) or None, "answered": bool}."""
    if _state["probe"] is not None:
        return _state["probe"]
    res = {"sixel": False, "cell": None, "answered": False}
    if sys.stdin.isatty() and sys.stdout.isatty():
        slow = bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))
        reply = _ask("\x1b[16t\x1b[14t\x1b[c", DA1, timeout=2.0 if slow else 0.6)
        m = DA1.search(reply)
        if m:
            res["answered"] = True
            res["sixel"] = "4" in m.group(1).split(";")
        c = re.search(r"\x1b\[6;(\d+);(\d+)t", reply)
        if c and int(c.group(1)) > 4 and int(c.group(2)) > 2:
            res["cell"] = (int(c.group(2)), int(c.group(1)))
        else:
            p = re.search(r"\x1b\[4;(\d+);(\d+)t", reply)
            if p:
                try:
                    size = os.get_terminal_size()
                    cell = (int(p.group(2)) // size.columns, int(p.group(1)) // size.lines)
                    if cell[0] > 2 and cell[1] > 4:
                        res["cell"] = cell
                except OSError:
                    pass
    _state["probe"] = res
    return res


def _ask(query, done_re, timeout):
    """Send a query and read the terminal's reply until done_re matches (raw mode, no echo)."""
    try:
        if os.name == "nt":
            return _ask_windows(query, done_re, timeout)
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        buf = ""
        try:
            tty.setcbreak(fd)
            sys.stdout.write(query)
            sys.stdout.flush()
            end = time.time() + timeout
            while time.time() < end and select.select([fd], [], [], max(0, end - time.time()))[0]:
                buf += os.read(fd, 1024).decode("latin-1")
                if done_re.search(buf):
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return buf
    except Exception:
        return ""


def _ask_windows(query, done_re, timeout):
    import ctypes
    import msvcrt
    k32 = ctypes.windll.kernel32
    h = k32.GetStdHandle(-10)
    mode = ctypes.c_uint()
    if not k32.GetConsoleMode(h, ctypes.byref(mode)):
        return ""
    k32.SetConsoleMode(h, (mode.value | 0x0200) & ~0x0006)  # VT input on, line input + echo off
    buf = ""
    try:
        sys.stdout.write(query)
        sys.stdout.flush()
        end = time.time() + timeout
        while time.time() < end:
            if msvcrt.kbhit():
                buf += msvcrt.getwch()
                if done_re.search(buf):
                    break
            else:
                time.sleep(0.005)
        return buf
    finally:
        k32.SetConsoleMode(h, mode.value)


def in_multiplexer():
    env = os.environ
    return bool(env.get("TMUX") or env.get("STY") or env.get("TERM", "").startswith(("screen", "tmux")))
