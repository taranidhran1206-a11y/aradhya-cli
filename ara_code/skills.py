"""Skills: her playbooks for recurring jobs, in the open SKILL.md format (agentskills.io).

A skill is a folder with a SKILL.md: YAML frontmatter (name, description) and plain instructions, plus optional
references/, templates/, scripts/ files. She sees every skill's name and description, loads the full skill when a
task matches, and writes or fixes skills herself after hard tasks.

Where they live (a project skill wins over yours when the names match):
  <project>/.aradhya/skills/   this project's skills (also read: .agents/skills, .claude/skills)
  ~/.aradhya/skills/           yours, everywhere (the starter skills are copied here once)
"""
import json
import re
import shutil
import time
from pathlib import Path

from . import engines

BUNDLED = Path(__file__).parent / "bundled_skills"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DESC_LIMIT = 160
SUPPORT_DIRS = ("references", "templates", "scripts", "assets")


def user_dir():
    return engines.HOME / "skills"


def project_dirs(cwd):
    cwd = Path(cwd)
    return [cwd / ".aradhya" / "skills", cwd / ".agents" / "skills", cwd / ".claude" / "skills"]


def seed():
    """Copy the starter skills into ~/.aradhya/skills once. Ones you delete stay deleted."""
    if not BUNDLED.exists():
        return
    target = user_dir()
    manifest = target / ".seeded.json"
    try:
        done = set(json.loads(manifest.read_text("utf-8")))
    except (OSError, ValueError):
        done = set()
    added = False
    for src in sorted(BUNDLED.iterdir()):
        if not (src / "SKILL.md").exists() or src.name in done:
            continue
        dst = target / src.name
        if not dst.exists():
            try:
                shutil.copytree(src, dst)
            except OSError:
                continue
        done.add(src.name)
        added = True
    if added:
        target.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(sorted(done)), "utf-8")


def parse(text):
    """(frontmatter dict, body). Understands the simple `key: value` YAML skills use."""
    meta, body = {}, text
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        body = m.group(2)
        key = None
        for line in m.group(1).splitlines():
            kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
            if kv:
                key, val = kv.group(1), kv.group(2).strip()
                if val in ("|", ">", "|-", ">-"):
                    val = ""
                meta[key] = val.strip().strip('"').strip("'")
            elif key and line.startswith((" ", "\t")) and line.strip():
                meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta, body


class Skill:
    def __init__(self, name, description, path, scope):
        self.name, self.description, self.path, self.scope = name, description, Path(path), scope

    @property
    def folder(self):
        return self.path.parent


def all_skills(cwd):
    """Every skill she can use here, project ones first. Names are unique (first one wins)."""
    found, seen = [], set()
    roots = [(d, "project") for d in project_dirs(cwd)] + [(user_dir(), "yours")]
    for root, scope in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("SKILL.md")):
            if any(part.startswith(".") for part in f.relative_to(root).parts[:-1]):
                continue  # .trash and friends
            try:
                meta, _ = parse(f.read_text("utf-8-sig", "replace")[:6000])
            except OSError:
                continue
            name = (meta.get("name") or f.parent.name).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            found.append(Skill(name, meta.get("description", "").strip(), f, scope))
    return found


def find(cwd, name):
    name = (name or "").strip().lstrip("/")
    for s in all_skills(cwd):
        if s.name == name or s.folder.name == name:
            return s
    return None


def index(cwd, limit=80):
    """The skills list that goes into her instructions."""
    skills = all_skills(cwd)
    if not skills:
        return ""
    lines = []
    for s in skills[:limit]:
        d = s.description if len(s.description) <= DESC_LIMIT else s.description[:DESC_LIMIT - 1] + "…"
        lines.append(f"- {s.name}: {d}" + ("  (this project)" if s.scope == "project" else ""))
    more = f"\n(and {len(skills) - limit} more; skill_view any name)" if len(skills) > limit else ""
    return "<available_skills>\n" + "\n".join(lines) + "\n</available_skills>" + more


def support_files(skill):
    out = []
    for f in sorted(skill.folder.rglob("*")):
        if f.is_file() and f.name != "SKILL.md" and not any(p.startswith(".") for p in f.relative_to(skill.folder).parts):
            out.append(str(f.relative_to(skill.folder)).replace("\\", "/"))
    return out[:50]


def _inside(folder, rel):
    p = (folder / rel).resolve()
    if rel.startswith(("/", "\\")) or ".." in Path(rel).parts or folder.resolve() not in [p, *p.parents]:
        raise ValueError("file_path must be a path inside the skill's folder, like references/api.md")
    return p


def view(cwd, name, file_path=None):
    s = find(cwd, name)
    if not s:
        names = ", ".join(x.name for x in all_skills(cwd)) or "none yet"
        return None, f"No skill called '{name}'. Skills: {names}"
    if file_path:
        p = _inside(s.folder, file_path)
        if not p.is_file():
            return s, f"{file_path} isn't in {s.name}. Files: {', '.join(support_files(s)) or 'none'}"
        return s, p.read_text("utf-8-sig", "replace")[:40000]
    text = s.path.read_text("utf-8-sig", "replace")
    extra = support_files(s)
    if extra:
        text += "\n\n[Files in this skill (read with skill_view file_path=…): " + ", ".join(extra) + "]"
    return s, text[:40000]


def check_skill_md(name, content):
    meta, body = parse(content)
    if not content.lstrip().startswith("---"):
        return "SKILL.md must start with frontmatter:\n---\nname: my-skill\ndescription: Use when …\n---"
    if meta.get("name") != name:
        return f"The frontmatter name must be '{name}' (it's '{meta.get('name', '')}')."
    desc = meta.get("description", "")
    if not desc:
        return "The frontmatter needs a description: one sentence saying when to use it."
    if len(desc) > DESC_LIMIT:
        return f"The description is {len(desc)} characters; keep it under {DESC_LIMIT}."
    if len(body.strip()) < 20:
        return "The skill needs instructions under the frontmatter."
    return None


def manage(cwd, action, name, content=None, old_string=None, new_string=None, replace_all=False,
           file_path=None, file_content=None, scope="user"):
    """Create or change a skill. Returns (ok, message, display) where display is for the transcript."""
    action = (action or "").lower()
    if not NAME_RE.match(name or ""):
        return False, "Skill names are lowercase letters, digits, - or _, up to 64 characters.", {}
    existing = find(cwd, name)
    if action == "create":
        if existing:
            return False, f"'{name}' already exists ({existing.path}). Use action 'patch' to improve it.", {}
        problem = check_skill_md(name, content or "")
        if problem:
            return False, problem, {}
        root = project_dirs(cwd)[0] if scope == "project" else user_dir()
        path = root / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((content.replace("\r\n", "\n").rstrip() + "\n").encode("utf-8"))
        return True, f"Created skill '{name}' at {path}", {"new": content, "path": str(path)}
    if not existing:
        return False, f"No skill called '{name}'. Create it first.", {}
    if action == "patch":
        target = _inside(existing.folder, file_path) if file_path else existing.path
        old_text = target.read_text("utf-8-sig", "replace").replace("\r\n", "\n") if target.exists() else ""
        if content is not None and old_string is None:
            if target == existing.path:
                problem = check_skill_md(name, content)
                if problem:
                    return False, problem, {}
            new_text = content.rstrip() + "\n"
        else:
            if not old_string:
                return False, "patch needs old_string and new_string (or content for a full rewrite).", {}
            n = old_text.count(old_string)
            if n == 0:
                return False, "old_string wasn't found. skill_view the skill and copy the text exactly.", {}
            if n > 1 and not replace_all:
                return False, f"old_string appears {n} times. Include more text, or set replace_all.", {}
            new_text = old_text.replace(old_string, new_string or "", -1 if replace_all else 1)
            if target == existing.path:
                problem = check_skill_md(name, new_text)
                if problem:
                    return False, "That would break the skill: " + problem, {}
        target.write_bytes(new_text.encode("utf-8"))
        from .tools import diff_text
        return True, f"Updated {name}/{target.relative_to(existing.folder).as_posix()}", \
            {"diff": diff_text(old_text, new_text, f"{name}/{target.name}")}
    if action == "write_file":
        if not file_path or file_content is None:
            return False, "write_file needs file_path (e.g. references/notes.md) and file_content.", {}
        target = _inside(existing.folder, file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_content.encode("utf-8"))
        return True, f"Wrote {name}/{file_path}", {"new": file_content, "path": str(target)}
    if action == "delete":
        trash = user_dir() / ".trash" / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
        trash.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(existing.folder), str(trash))
        return True, f"Deleted '{name}' (moved to {trash}, in case you want it back)", {}
    return False, f"Unknown action '{action}'. Use create, patch, write_file or delete.", {}


LEARN_PROMPT = """Turn {what} into a reusable skill with skill_manage (action "create"), so next time you can follow it
instead of working it out again. Load the skill-authoring skill first if you have it.

- name: short, lowercase-with-hyphens, describing the job (not the project).
- description: ONE sentence under 160 characters starting "Use when", saying when it applies.
- body: when to use it, the steps that actually worked (exact commands), pitfalls you hit and how you got past
  them, and how to check it worked. Write rules and lessons, not a diary of this session.
- If a skill for this job already exists, improve it with action "patch" instead of making another.
Tell me the skill's name in one line when you're done."""


def learn_prompt(what):
    return LEARN_PROMPT.format(what=what.strip() if what and what.strip() else "what we just did in this session")


def use_prompt(name, args):
    task = args.strip() if args and args.strip() else "the task it describes, here"
    return f'Use the "{name}" skill: load it with skill_view and follow it. Task: {task}'
