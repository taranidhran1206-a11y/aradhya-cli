"""Aradhya Code tests with a scripted model (no network). Run: python3 -m unittest tests.test_ara_code"""
import os
import tempfile
import unittest
from pathlib import Path

from ara_code.agent import Agent, build_system
from ara_code.providers import ScriptedProvider, OpenAIProvider
from ara_code.tools import ToolBox, is_safe_command, command_prefix


class FakeUI:
    persona = "aradhya"

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.asked = []
        self.lines = []
        self.todos = None

    def assistant_start(self): pass
    def assistant_delta(self, t): pass
    def assistant_end(self, t): self.lines.append(("say", t))
    def tool_start(self, label, ro): self.lines.append(("tool", label))
    def tool_end(self, summary, ok, display=None): self.lines.append(("done", summary, ok))
    def error(self, m): self.lines.append(("error", m))
    def show_todos(self, todos): self.todos = todos

    def ask_permission(self, title, preview, tool, prefix):
        self.asked.append((title, preview, tool, prefix))
        return self.answers.pop(0) if self.answers else ("yes", "")


def call(name, args, i=0):
    return ("tool_call", {"id": f"c{i}", "name": name, "args": args, "sig": None})


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "calc.py").write_text("def add(a, b):\n    return a - b\n")
        (self.dir / "test_calc.py").write_text(
            "from calc import add\nassert add(2, 3) == 5\nprint('tests pass')\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fix_bug_end_to_end(self):
        script = [
            [("text", "Let me look."), call("todo_write", {"todos": [
                {"content": "Find the bug", "status": "in_progress"},
                {"content": "Fix and test", "status": "pending"}]}),
             call("grep", {"pattern": "def add"}, 1), call("read_file", {"path": "calc.py"}, 2)],
            [call("edit_file", {"path": "calc.py", "old_string": "a - b", "new_string": "a + b"}, 3)],
            [call("bash", {"command": "python3 test_calc.py"}, 4)],
            [("text", "Fixed `calc.py:2`: it subtracted instead of adding. Tests pass.")],
        ]
        ui = FakeUI()
        agent = Agent(ScriptedProvider(script), ToolBox(self.dir, ui), ui)
        agent.run("the add test fails, fix it")
        self.assertIn("a + b", (self.dir / "calc.py").read_text())
        results = [m for m in agent.history if m["role"] == "tool"]
        self.assertEqual(len(results), 5)
        self.assertIn("tests pass", results[-1]["result"])
        self.assertIn("calc.py:1", results[1]["result"])
        self.assertEqual(agent.tools.todos[0]["status"], "in_progress")
        # edit asked once, python run asked once; grep/read never asked
        self.assertEqual([a[2] for a in ui.asked], ["edit_file", "bash"])
        self.assertTrue(agent.history[-1]["text"].startswith("Fixed"))

    def test_edit_requires_read_first(self):
        ui = FakeUI()
        box = ToolBox(self.dir, ui, "yolo")
        r = box.run("edit_file", {"path": "calc.py", "old_string": "a - b", "new_string": "a + b"})
        self.assertFalse(r.ok)
        self.assertIn("Read", r.output)

    def test_reject_with_feedback_continues_and_plain_reject_stops(self):
        script = [
            [call("read_file", {"path": "calc.py"}), call("edit_file", {"path": "calc.py", "old_string": "a - b",
                                                                         "new_string": "b - a"}, 1)],
            [call("edit_file", {"path": "calc.py", "old_string": "a - b", "new_string": "a + b"}, 2)],
            [call("bash", {"command": "rm -rf build"}, 3), call("bash", {"command": "echo hi"}, 4)],
            [("text", "should not be reached")],
        ]
        ui = FakeUI([("no", "use a + b instead"), ("yes", ""), ("no", "")])
        p = ScriptedProvider(script)
        agent = Agent(p, ToolBox(self.dir, ui), ui)
        agent.run("fix add")
        self.assertIn("a + b", (self.dir / "calc.py").read_text())
        tool_msgs = [m for m in agent.history if m["role"] == "tool"]
        self.assertIn("use a + b instead", tool_msgs[1]["result"])
        self.assertIn("Stop", tool_msgs[3]["result"])
        self.assertIn("Skipped", tool_msgs[4]["result"])
        self.assertEqual(len(p.turns), 1)  # stopped, didn't ask the model again

    def test_always_allow_command_prefix(self):
        ui = FakeUI([("always", "")])
        box = ToolBox(self.dir, ui)
        box.run("bash", {"command": "python3 -c 'print(1)'"})
        box.run("bash", {"command": "python3 -c 'print(2)'"})
        self.assertEqual(len(ui.asked), 1)

    def test_cd_persists(self):
        (self.dir / "sub").mkdir()
        box = ToolBox(self.dir, FakeUI(), "yolo")
        box.run("bash", {"command": "cd sub"})
        self.assertEqual(box.cwd, (self.dir / "sub").resolve())
        r = box.run("bash", {"command": "pwd"})
        self.assertIn("sub", r.output)

    def test_exit_code_reported(self):
        box = ToolBox(self.dir, FakeUI(), "yolo")
        r = box.run("bash", {"command": "exit 3"})
        self.assertFalse(r.ok)
        self.assertIn("exit code 3", r.output)

    def test_write_new_file_and_list(self):
        ui = FakeUI()
        box = ToolBox(self.dir, ui)
        r = box.run("write_file", {"path": "pkg/new.py", "content": "x = 1\n"})
        self.assertTrue(r.ok)
        self.assertEqual(ui.asked[0][1]["kind"], "new")
        r = box.run("list_files", {"pattern": "**/*.py"})
        self.assertIn("pkg/new.py", r.output.replace("\\", "/"))

    def test_overwrite_needs_read(self):
        box = ToolBox(self.dir, FakeUI(), "yolo")
        self.assertFalse(box.run("write_file", {"path": "calc.py", "content": "x"}).ok)

    def test_ambiguous_edit(self):
        (self.dir / "d.txt").write_text("a\na\n")
        box = ToolBox(self.dir, FakeUI(), "yolo")
        box.run("read_file", {"path": "d.txt"})
        r = box.run("edit_file", {"path": "d.txt", "old_string": "a", "new_string": "b"})
        self.assertIn("2 times", r.output)
        r = box.run("edit_file", {"path": "d.txt", "old_string": "a", "new_string": "b", "replace_all": True})
        self.assertTrue(r.ok)
        self.assertEqual((self.dir / "d.txt").read_text(), "b\nb\n")

    def test_safe_commands(self):
        self.assertTrue(is_safe_command("git status && ls -la"))
        self.assertTrue(is_safe_command("grep -rn foo . | head"))
        self.assertFalse(is_safe_command("ls > out.txt"))
        self.assertFalse(is_safe_command("rm -rf /"))
        self.assertFalse(is_safe_command("git push"))
        self.assertFalse(is_safe_command("cat $(whoami)"))
        self.assertEqual(command_prefix("git commit -m hi"), "git commit")
        self.assertEqual(command_prefix("pytest -q"), "pytest")

    def test_project_memory_in_system_prompt(self):
        (self.dir / ".git").mkdir()
        (self.dir / "ARADHYA.md").write_text("Always use tabs.")
        s = build_system(self.dir)
        self.assertIn("Always use tabs.", s)
        self.assertIn(str(self.dir), s)

    def test_compact(self):
        ui = FakeUI()
        p = ScriptedProvider([[("text", "hi")], [("text", "Goal: fix add. Done.")]])
        agent = Agent(p, ToolBox(self.dir, ui), ui)
        agent.run("hello")
        self.assertTrue(agent.compact())
        self.assertEqual(len(agent.history), 2)
        self.assertIn("Goal: fix add", agent.history[0]["text"])

    def test_openai_message_conversion(self):
        p = OpenAIProvider(base_url="http://x/v1")
        hist = [{"role": "user", "text": "hi"},
                {"role": "assistant", "text": "", "tool_calls": [{"id": "1", "name": "grep", "args": {"pattern": "x"}}]},
                {"role": "tool", "id": "1", "name": "grep", "result": "none"}]
        msgs = p._messages(hist, "sys")
        self.assertEqual(msgs[2]["tool_calls"][0]["function"]["name"], "grep")
        self.assertEqual(msgs[3], {"role": "tool", "tool_call_id": "1", "content": "none"})


class GeminiConversionTest(unittest.TestCase):
    HIST = [{"role": "user", "text": "hi"},
            {"role": "assistant", "text": "look", "tool_calls": [
                {"id": "1", "gid": "g1", "name": "grep", "args": {"pattern": "x"}, "sig": "c2ln"},
                {"id": "2", "name": "read_file", "args": {"path": "a"}, "sig": None}]},
            {"role": "tool", "id": "1", "gid": "g1", "name": "grep", "result": "r1"},
            {"role": "tool", "id": "2", "name": "read_file", "result": "r2"},
            {"role": "assistant", "text": "done", "tool_calls": []}]

    def test_rest_contents(self):
        """The SDK-free path used on Termux."""
        from ara_code.providers import GeminiProvider
        c = GeminiProvider._rest_contents(self.HIST)
        self.assertEqual([x["role"] for x in c], ["user", "model", "user", "model"])
        self.assertEqual(c[1]["parts"][1], {"functionCall": {"name": "grep", "args": {"pattern": "x"}, "id": "g1"},
                                            "thoughtSignature": "c2ln"})
        self.assertEqual(c[2]["parts"][0]["functionResponse"]["id"], "g1")
        self.assertEqual(len(c[2]["parts"]), 2)

    def test_contents(self):
        try:
            import google.genai  # noqa: F401
        except ImportError:
            self.skipTest("google-genai not installed (minimal install)")
        from ara_code.providers import GeminiProvider
        os.environ.setdefault("GEMINI_API_KEY", "test")
        g = GeminiProvider()
        hist = [{"role": "user", "text": "hi"},
                {"role": "assistant", "text": "look", "tool_calls": [
                    {"id": "1", "name": "grep", "args": {"pattern": "x"}, "sig": "c2ln"},
                    {"id": "2", "name": "read_file", "args": {"path": "a"}, "sig": None}]},
                {"role": "tool", "id": "1", "name": "grep", "result": "r1"},
                {"role": "tool", "id": "2", "name": "read_file", "result": "r2"},
                {"role": "assistant", "text": "done", "tool_calls": []}]
        c = g._contents(hist)
        self.assertEqual([x.role for x in c], ["user", "model", "user", "model"])
        self.assertEqual(len(c[2].parts), 2)
        self.assertEqual(c[1].parts[1].thought_signature, b"sig")


if __name__ == "__main__":
    unittest.main()


class LogoImageTests(unittest.TestCase):
    def test_protocols(self):
        from ara_code import logo_img
        import importlib.util
        os.environ["ARA_CELL_PX"] = "10x20"
        logo_img._cell = None
        s = logo_img.render("sixel", 24, 12)
        if importlib.util.find_spec("PIL"):
            self.assertTrue(s.startswith("\x1bP0;1;0q") and s.endswith("\x1b\\"))
            self.assertIn('"1;1;222;222', s)  # 94% of a 240x240 box, rounded to whole sixel bands
        else:
            self.assertEqual(s, "")  # no Pillow: falls back to block art
        k = logo_img.render("kitty", 24, 12)
        self.assertIn("c=24,r=12", k)
        self.assertTrue(logo_img.render("iterm", 24, 12).startswith("\x1b]1337;File=inline=1;width=24;height=12"))
        self.assertEqual(logo_img.render("blocks", 24, 12), "")

    def test_detect(self):
        from ara_code import logo_img
        os.environ["ARA_LOGO"] = "blocks"
        self.assertEqual(logo_img.detect(), "blocks")
        del os.environ["ARA_LOGO"]
