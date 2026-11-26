"""SOUL.md, memory, skills, session search and helper agents."""
import importlib
import json
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_ara_code import FakeUI, call  # noqa: E402


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.home = Path(self.tmp.name, "home")
        self.proj = Path(self.tmp.name, "proj")
        self.proj.mkdir()
        self.old = dict(os.environ)
        os.environ["ARA_HOME"] = str(self.home)
        import ara_code.engines, ara_code.soul, ara_code.skills, ara_code.tools, ara_code.agent
        importlib.reload(ara_code.engines)
        self.soul = importlib.reload(ara_code.soul)
        self.skills = importlib.reload(ara_code.skills)
        self.tools = importlib.reload(ara_code.tools)
        self.agent = importlib.reload(ara_code.agent)
        from ara_code.providers import ScriptedProvider
        self.Scripted = ScriptedProvider

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)
        self.tmp.cleanup()

    # ── soul ──
    def test_soul_is_written_once_and_read_with_the_name(self):
        self.soul.ensure_soul()
        p = self.soul.soul_path("aradhya")
        self.assertTrue(p.exists() and self.soul.soul_path("leo").exists())
        text = self.soul.load_soul("aradhya", "Meera")
        self.assertIn("Meera's own AI", text)
        self.assertNotIn("<!--", text)
        p.write_text("<!-- note -->\nYou are Aradhya, a pirate who codes for {name}.")
        self.assertEqual(self.soul.load_soul("aradhya", "Meera"), "You are Aradhya, a pirate who codes for Meera.")
        sysprompt = self.agent.build_system(self.proj, "aradhya", "Meera")
        self.assertTrue(sysprompt.startswith("You are Aradhya, a pirate"))
        self.soul.ensure_soul()  # doesn't overwrite your edits
        self.assertIn("pirate", p.read_text())

    # ── memory ──
    def test_memory_add_patch_remove_and_limit(self):
        ok, msg, ch = self.soul.apply("user", [{"action": "add", "content": "Prefers pytest over unittest"},
                                               {"action": "add", "content": "Works on Windows with WSL"}])
        self.assertTrue(ok)
        self.assertEqual(len(ch), 2)
        ok, _, _ = self.soul.apply("user", [{"action": "patch", "old_text": "WSL", "content": "WSL2"}])
        self.assertIn("Works on Windows with WSL2", self.soul.entries("user"))
        ok, _, _ = self.soul.apply("user", [{"action": "remove", "old_text": "pytest"}])
        self.assertEqual(self.soul.entries("user"), ["Works on Windows with WSL2"])
        ok, msg, _ = self.soul.apply("user", [{"action": "add", "content": "x" * 2000}])
        self.assertFalse(ok)
        self.assertIn("limit", msg)
        self.assertIn("Works on Windows with WSL2", msg)  # shows what's there so she can tidy up
        ok, msg, _ = self.soul.apply("memory", [{"action": "remove", "old_text": "nope"}])
        self.assertFalse(ok)
        block = self.soul.prompt_block("Meera")
        self.assertIn("What you know about Meera", block)
        self.assertIn("WSL2", self.agent.build_system(self.proj, "aradhya", "Meera"))

    def test_memory_tool_through_the_toolbox(self):
        tb = self.tools.ToolBox(self.proj, FakeUI())
        r = tb.run("memory", {"target": "memory", "operations": [{"action": "add", "content": "Repo uses uv"}]})
        self.assertTrue(r.ok)
        self.assertIn("Remembered: Repo uses uv", r.summary)
        r = tb.run("memory", {"target": "memory", "operations": [{"action": "add", "content": "Repo uses uv"}]})
        self.assertEqual(r.summary, "Already knew that")
        self.assertEqual(tb.label("memory", {"target": "user"}), "Remember(about you)")

    # ── skills ──
    SKILL = "---\nname: deploy-ec2\ndescription: Use when deploying the app to the EC2 box.\n---\n\n1. ssh in\n2. git pull\n"

    def test_seeded_skills_show_up_and_deleted_ones_stay_deleted(self):
        self.skills.seed()
        names = {s.name for s in self.skills.all_skills(self.proj)}
        self.assertTrue({"skill-authoring", "commit-message", "code-review", "fix-failing-test"} <= names)
        idx = self.skills.index(self.proj)
        self.assertIn("- code-review: Use when", idx)
        import shutil
        shutil.rmtree(self.skills.user_dir() / "code-review")
        self.skills.seed()
        self.assertIsNone(self.skills.find(self.proj, "code-review"))

    def test_create_view_patch_and_delete_a_skill(self):
        ui = FakeUI()
        tb = self.tools.ToolBox(self.proj, ui)
        r = tb.run("skill_manage", {"action": "create", "name": "deploy-ec2", "content": self.SKILL})
        self.assertTrue(r.ok, r.output)
        self.assertIn("new", r.display)
        self.assertEqual(ui.asked, [])  # your own skills don't need asking
        bad = tb.run("skill_manage", {"action": "create", "name": "bad", "content": "no frontmatter here at all"})
        self.assertFalse(bad.ok)
        dup = tb.run("skill_manage", {"action": "create", "name": "deploy-ec2", "content": self.SKILL})
        self.assertIn("patch", dup.output)
        r = tb.run("skill_view", {"name": "deploy-ec2"})
        self.assertIn("git pull", r.output)
        r = tb.run("skill_manage", {"action": "patch", "name": "deploy-ec2", "old_string": "2. git pull",
                                    "new_string": "2. git pull --ff-only\n3. systemctl restart app"})
        self.assertTrue(r.ok, r.output)
        self.assertIn("diff", r.display)
        r = tb.run("skill_manage", {"action": "write_file", "name": "deploy-ec2", "file_path": "references/hosts.md",
                                    "file_content": "prod: 1.2.3.4"})
        self.assertTrue(r.ok)
        self.assertIn("references/hosts.md", tb.run("skill_view", {"name": "deploy-ec2"}).output)
        self.assertEqual(tb.run("skill_view", {"name": "deploy-ec2", "file_path": "references/hosts.md"}).output,
                         "prod: 1.2.3.4")
        escape = tb.run("skill_view", {"name": "deploy-ec2", "file_path": "../../../etc/passwd"})
        self.assertFalse(escape.ok)
        r = tb.run("skill_manage", {"action": "delete", "name": "deploy-ec2"})
        self.assertTrue(r.ok)
        self.assertEqual(len(ui.asked), 1)  # deleting asks
        self.assertIsNone(self.skills.find(self.proj, "deploy-ec2"))
        self.assertTrue(any((self.skills.user_dir() / ".trash").iterdir()))

    def test_project_skills_win_and_ask_before_writing_into_the_project(self):
        ui = FakeUI(answers=[("yes", "")])
        tb = self.tools.ToolBox(self.proj, ui)
        r = tb.run("skill_manage", {"action": "create", "name": "deploy-ec2", "content": self.SKILL, "scope": "project"})
        self.assertTrue(r.ok, r.output)
        self.assertEqual(len(ui.asked), 1)
        self.assertTrue((self.proj / ".aradhya" / "skills" / "deploy-ec2" / "SKILL.md").exists())
        self.assertEqual(self.skills.find(self.proj, "deploy-ec2").scope, "project")
        (self.proj / ".claude" / "skills" / "lint").mkdir(parents=True)
        (self.proj / ".claude" / "skills" / "lint" / "SKILL.md").write_text(
            "---\nname: lint\ndescription: Use when linting.\n---\nRun ruff.")
        self.assertIsNotNone(self.skills.find(self.proj, "lint"))

    def test_skills_and_learning_rules_reach_her_instructions(self):
        self.skills.seed()
        s = self.agent.build_system(self.proj, "aradhya", "Meera")
        self.assertIn("# Skills", s)
        self.assertIn("skill_view", s)
        self.assertIn("who Meera is", s)

    # ── session search ──
    def test_session_search_finds_earlier_conversations(self):
        folder = self.home / "sessions"
        folder.mkdir(parents=True)
        (folder / "20261101-100000.json").write_text(json.dumps({
            "cwd": "/work/api", "updated": time.time() - 86400, "title": "fix the nginx config",
            "history": [{"role": "user", "text": "the nginx reverse proxy returns 502"},
                        {"role": "assistant", "text": "Fixed: proxy_pass pointed at port 8000 instead of 8642."}]}))
        (folder / "20261102-100000.json").write_text(json.dumps({
            "cwd": "/work/web", "updated": time.time(), "title": "css", "history": [{"role": "user", "text": "center a div"}]}))
        tb = self.tools.ToolBox(self.proj, FakeUI())
        r = tb.run("session_search", {"query": "nginx 8642"})
        self.assertTrue(r.ok)
        self.assertIn("fix the nginx config", r.output)
        self.assertIn("8642", r.output)
        self.assertNotIn("center a div", r.output)
        self.assertEqual(tb.run("session_search", {"query": "kubernetes"}).summary, "Nothing found")

    # ── helpers ──
    def test_delegate_runs_a_helper_with_a_fresh_context(self):
        (self.proj / "app.py").write_text("PORT = 8642\n")
        script = [
            [call("delegate", {"task": "Find which port the app uses", "context": "Look in app.py"})],
            [call("read_file", {"path": "app.py"}, 1)],          # the helper's turn
            [("text", "The app uses port 8642 (app.py:1).")],     # the helper's report
            [("text", "It's port 8642.")],                        # back in the main agent
        ]
        p = self.Scripted(script)
        ui = FakeUI()
        tb = self.tools.ToolBox(self.proj, ui)
        a = self.agent.Agent(p, tb, ui)
        a.run("what port?")
        helper_history = p.seen[1]
        self.assertEqual(helper_history[0]["role"], "user")
        self.assertIn("Find which port", helper_history[0]["text"])
        self.assertNotIn("what port?", json.dumps(helper_history))  # fresh context
        tool_result = next(m for m in a.history if m["role"] == "tool" and m["name"] == "delegate")
        self.assertIn("8642 (app.py:1)", tool_result["result"])
        self.assertIn(("done", "Helper finished in 1 step", True), ui.lines)
        self.assertEqual(a.history[-1]["text"], "It's port 8642.")
        self.assertIsNotNone(tb.delegate_fn)  # restored after the helper finished

    def test_helpers_cant_delegate_or_rewrite_memory(self):
        names = {t["name"] for t in self.tools.HELPER_TOOLS}
        self.assertFalse(names & {"delegate", "memory", "skill_manage"})
        self.assertIn("skill_view", names)

    def test_learn_and_use_prompts(self):
        self.assertIn("what we just did", self.skills.learn_prompt(""))
        self.assertIn("the deploy flow", self.skills.learn_prompt("the deploy flow"))
        self.assertIn('"code-review" skill', self.skills.use_prompt("code-review", "my branch"))


if __name__ == "__main__":
    unittest.main()
