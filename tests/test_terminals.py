"""Terminals and text: encodings, line endings, plain symbols, the terminal probe and how her logo is drawn."""
import importlib
import io
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_ara_code import FakeUI  # noqa: E402


class TextFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        from ara_code.tools import ToolBox, TextFile
        self.TextFile = TextFile
        self.tb = ToolBox(self.dir, FakeUI())

    def tearDown(self):
        self.tmp.cleanup()

    def edit(self, name, old, new):
        self.assertTrue(self.tb.run("read_file", {"path": name}).ok)
        r = self.tb.run("edit_file", {"path": name, "old_string": old, "new_string": new})
        self.assertTrue(r.ok, r.output)
        return (self.dir / name).read_bytes()

    def test_windows_line_endings_stay_windows(self):
        (self.dir / "a.txt").write_bytes(b"one\r\ntwo\r\nthree\r\n")
        self.assertEqual(self.edit("a.txt", "two", "2\nand a half"), b"one\r\n2\r\nand a half\r\nthree\r\n")

    def test_unix_line_endings_stay_unix(self):
        (self.dir / "b.py").write_bytes(b"x = 1\ny = 2\n")
        self.assertEqual(self.edit("b.py", "y = 2", "y = 3"), b"x = 1\ny = 3\n")

    def test_utf16_from_powershell_is_text_not_binary(self):
        (self.dir / "log.txt").write_bytes("﻿hello வணக்கம்\r\nok\r\n".encode("utf-16-le")[0:0] +
                                           b"\xff\xfe" + "hello வணக்கம்\r\nok\r\n".encode("utf-16-le"))
        r = self.tb.run("read_file", {"path": "log.txt"})
        self.assertTrue(r.ok)
        self.assertIn("வணக்கம்", r.output)
        out = self.edit("log.txt", "ok", "done")
        self.assertTrue(out.startswith(b"\xff\xfe"))
        self.assertEqual(out[2:].decode("utf-16-le"), "hello வணக்கம்\r\ndone\r\n")

    def test_bom_and_old_windows_encodings_are_kept(self):
        (self.dir / "bom.cs").write_bytes(b"\xef\xbb\xbfclass A {}\r\n")
        self.assertEqual(self.edit("bom.cs", "A", "B"), b"\xef\xbb\xbfclass B {}\r\n")
        (self.dir / "old.txt").write_bytes("café\n".encode("cp1252"))
        self.assertIn("café", self.tb.run("read_file", {"path": "old.txt"}).output)
        self.assertEqual(self.edit("old.txt", "café", "cafés"), "cafés\n".encode("cp1252"))
        # a character cp1252 can't hold: the file becomes UTF-8 rather than losing it
        self.assertEqual(self.edit("old.txt", "cafés", "காபி"), "காபி\n".encode("utf-8"))

    def test_real_binary_is_still_refused(self):
        (self.dir / "x.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)))
        self.assertFalse(self.tb.run("read_file", {"path": "x.bin"}).ok)

    def test_new_files_use_plain_newlines(self):
        r = self.tb.run("write_file", {"path": "new.txt", "content": "a\r\nb\n"})
        self.assertTrue(r.ok)
        self.assertEqual((self.dir / "new.txt").read_bytes(), b"a\nb\n")

    def test_command_output_is_utf8(self):
        from ara_code.tools import child_env, decode_output
        env = child_env()
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(env[f"GIT_CONFIG_KEY_{int(env['GIT_CONFIG_COUNT']) - 1}"], "core.quotepath")
        self.assertEqual(decode_output("﻿hi".encode("utf-8")), "hi")
        self.assertEqual(decode_output(b"caf\xc3\xa9 \xff"), "café �")
        if os.name != "nt":
            r = self.tb.run("bash", {"command": "python3 -c \"print('வணக்கம் ✓')\""})
            self.assertIn("வணக்கம் ✓", r.output)


class SymbolTests(unittest.TestCase):
    def test_plain_symbols_keep_their_width(self):
        from rich.cells import cell_len
        from ara_code.termcaps import PLAIN
        for fancy, plain in PLAIN.items():
            self.assertEqual(cell_len(fancy), cell_len(plain), f"{fancy!r} -> {plain!r}")

    def test_plain_stream_swaps_symbols_and_hides_buffer(self):
        from ara_code.termcaps import PlainStream
        raw = io.StringIO()
        s = PlainStream(raw)
        s.write("✦ Aradhya ╭─╮ ⎿ ✓ ❯")
        self.assertEqual(raw.getvalue(), "♦ Aradhya ┌─┐ └ √ ►")
        self.assertFalse(hasattr(s, "buffer"))  # so prompt_toolkit writes through it

    def test_when_plain_symbols_are_used(self):
        import ara_code.termcaps as t
        cases = [({"ARA_ASCII": "1"}, "nt", None, True), ({"ARA_ASCII": "0", "TERM": "linux"}, "posix", None, False),
                 ({"WT_SESSION": "x"}, "nt", "Consolas", False), ({}, "nt", "Consolas", True),
                 ({}, "nt", "Cascadia Mono", False), ({"TERM": "linux"}, "posix", None, True),
                 ({"TERM": "xterm-256color"}, "posix", None, False)]
        for env, osname, font, want in cases:
            t._state["plain"] = None
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(t.os, "name", osname), \
                    mock.patch.object(t, "console_font", lambda: font or ""):
                self.assertEqual(t.plain_symbols(), want, (env, osname, font))
        t._state["plain"] = None


class ProbeTests(unittest.TestCase):
    def setUp(self):
        import ara_code.termcaps as t
        self.t = t
        t._state["probe"] = None

    def tearDown(self):
        self.t._state["probe"] = None

    def run_probe(self, reply):
        with mock.patch.object(self.t, "_ask", lambda q, r, timeout: reply), \
                mock.patch.object(sys.stdin, "isatty", lambda: True), mock.patch.object(sys.stdout, "isatty", lambda: True), \
                mock.patch.object(self.t.os, "get_terminal_size", lambda *a: os.terminal_size((100, 30))):
            return self.t.probe()

    def test_sixel_and_cell_size_in_one_answer(self):
        res = self.run_probe("\x1b[6;21;10t\x1b[4;630;1000t\x1b[?62;4;22c")
        self.assertEqual(res, {"sixel": True, "cell": (10, 21), "answered": True})

    def test_window_size_when_cell_size_isnt_answered(self):
        res = self.run_probe("\x1b[4;600;1200t\x1b[?62;4c")
        self.assertEqual(res["cell"], (12, 20))

    def test_no_sixel(self):
        res = self.run_probe("\x1b[?1;2c")
        self.assertFalse(res["sixel"])
        self.assertTrue(res["answered"])

    def test_the_question_ends_with_device_attributes(self):
        seen = {}

        def fake(q, r, timeout):
            seen["q"], seen["t"] = q, timeout
            return ""
        with mock.patch.object(self.t, "_ask", fake), mock.patch.object(sys.stdin, "isatty", lambda: True), \
                mock.patch.object(sys.stdout, "isatty", lambda: True), mock.patch.dict(os.environ, {"SSH_TTY": "/dev/pts/1"}):
            self.t.probe()
        self.assertTrue(seen["q"].endswith("\x1b[c"))  # every terminal answers this last, so nothing arrives late
        self.assertGreaterEqual(seen["t"], 2.0)          # and a slow SSH link gets longer


class LogoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        os.environ["ARA_HOME"] = self.tmp.name
        import ara_code.engines, ara_code.logo_img, ara_code.termcaps
        importlib.reload(ara_code.engines)
        self.li = importlib.reload(ara_code.logo_img)
        self.t = ara_code.termcaps
        self.t._state.update(plain=False, probe={"sixel": True, "cell": (10, 21), "answered": True})

    def tearDown(self):
        self.t._state.update(plain=None, probe=None)
        os.environ.pop("ARA_HOME", None)
        self.tmp.cleanup()

    def detect(self, env):
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(sys.stdin, "isatty", lambda: True), \
                mock.patch.object(sys.stdout, "isatty", lambda: True):
            for k in ("ARA_LOGO", "KITTY_WINDOW_ID", "TERM_PROGRAM", "TMUX", "LC_TERMINAL", "ARA_CELL_PX", "WT_SESSION"):
                if k not in env:
                    os.environ.pop(k, None)
            return self.li.detect()

    def test_choices(self):
        self.assertEqual(self.detect({"KITTY_WINDOW_ID": "1"}), "kitty")
        self.assertEqual(self.detect({"TERM_PROGRAM": "WezTerm"}), "iterm")
        self.assertEqual(self.detect({}), "sixel")
        self.assertEqual(self.detect({"KITTY_WINDOW_ID": "1", "TMUX": "/tmp/t,1,0"}), "sixel")  # tmux: no kitty
        self.assertEqual(self.detect({"ARA_LOGO": "blocks"}), "blocks")
        self.t._state["probe"] = {"sixel": True, "cell": None, "answered": True}
        self.assertEqual(self.detect({}), "blocks")  # can't size a sixel picture without the cell size
        self.assertEqual(self.detect({"WT_SESSION": "1"}), "sixel")  # Windows Terminal's default font
        self.t._state["plain"] = True
        self.assertEqual(self.detect({"KITTY_WINDOW_ID": "1"}), "blocks")

    def test_saying_no_in_setup_sticks(self):
        from ara_code import engines
        engines.save_config(logo="blocks")
        self.assertEqual(self.detect({}), "blocks")
        engines.save_config(logo="picture")
        self.assertEqual(self.detect({}), "sixel")

    def test_logo_sizes(self):
        from ara_code.ui import logo_size, logo_text
        self.assertEqual([logo_size(n) for n in (30, 20, 13, 12, 11)], [24, 20, 12, 12, 0])
        self.assertEqual(len(logo_text(12)), 6)

    def test_too_tall_for_the_screen_falls_back_to_blocks(self):
        from rich.console import Console
        from ara_code.ui import TerminalUI
        ui = TerminalUI(interactive=False)
        ui.console = Console(file=io.StringIO(), width=100, color_system="truecolor", force_terminal=True)
        with mock.patch.object(self.li, "detect", lambda: "sixel"), \
                mock.patch.object(self.li, "render", lambda k, c, r: "\x1bPq#0;2;0;0;0#0~\x1b\\"), \
                mock.patch("os.get_terminal_size", lambda *a: os.terminal_size((100, 10))):
            ui.setup_card("Hi", ["a", "b"])
        out = ui.console.file.getvalue()
        self.assertNotIn("\x1bP", out)        # no picture
        self.assertIn("▀", out)               # block art instead of a blank gap
        with mock.patch.object(self.li, "detect", lambda: "sixel"), \
                mock.patch.object(self.li, "render", lambda k, c, r: "\x1bPq#0;2;0;0;0#0~\x1b\\"), \
                mock.patch("os.get_terminal_size", lambda *a: os.terminal_size((100, 50))):
            ui.console.file = io.StringIO()
            ui.setup_card("Hi", ["a", "b"])
        self.assertIn("\x1bP", ui.console.file.getvalue())  # room for it: the real picture


if __name__ == "__main__":
    unittest.main()
