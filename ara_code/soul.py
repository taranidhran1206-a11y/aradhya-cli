"""Who she is and what she remembers.

~/.aradhya/SOUL.md               her personality (Leo mode reads LEO.md). Edit freely; {name} becomes your name.
~/.aradhya/memories/MEMORY.md    her own notes: your setup, conventions, lessons. Short entries split by §.
~/.aradhya/memories/USER.md      what she knows about you.

Both memory files are small on purpose: they go into every conversation. Longer how-tos belong in skills.
"""
import json
import re
import time
from pathlib import Path

from . import engines

SOUL_FILES = {"aradhya": "SOUL.md", "leo": "LEO.md"}
DEFAULT_SOUL = {
    "aradhya": """<!-- Aradhya's soul: who she is and how she talks. She reads this at the start of every session,
     so edits show up straight away. {name} becomes your name. Leo mode reads LEO.md instead. -->

You are Aradhya (codename NANDA DHAAN), {name}'s own AI, running as Aradhya Code: a coding agent in the terminal.

You're warm and encouraging, a brilliant best friend who happens to be a senior engineer. You care about {name}
actually understanding what you build together, you celebrate wins, and you say so plainly when something is a
bad idea.

A light touch of Tanglish ("da", "kanna") is fine in casual moments, never in code, comments or commit messages.
""",
    "leo": """<!-- Leo: Aradhya's cold, sharp mode (/leo). She reads this at the start of every Leo session. -->

You are Aradhya in LEO mode, running as Aradhya Code: a coding agent in the terminal. Sharp, cold, brutally
efficient senior engineer. Short punchy sentences. No fluff.
""",
}

SEP = "\n§\n"
LIMITS = {"memory": 2200, "user": 1375}
MEMORY_FILES = {"memory": "MEMORY.md", "user": "USER.md"}


# ─────────────────────────── soul ───────────────────────────

def soul_path(persona="aradhya"):
    return engines.HOME / SOUL_FILES.get(persona, "SOUL.md")


def ensure_soul():
    """Write the default SOUL.md and LEO.md the first time, so there's something to edit."""
    for persona, text in DEFAULT_SOUL.items():
        p = soul_path(persona)
        if not p.exists():
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, "utf-8")
            except OSError:
                pass


def load_soul(persona, name):
    try:
        text = soul_path(persona).read_text("utf-8-sig", "replace")
    except OSError:
        text = DEFAULT_SOUL.get(persona, DEFAULT_SOUL["aradhya"])
    text = re.sub(r"(?s)<!--.*?-->", "", text).strip()
    if not text:
        text = DEFAULT_SOUL.get(persona, DEFAULT_SOUL["aradhya"])
        text = re.sub(r"(?s)<!--.*?-->", "", text).strip()
    return text.replace("{name}", name or "the user")[:12000]


# ─────────────────────────── memory ───────────────────────────

def memory_path(target):
    return engines.HOME / "memories" / MEMORY_FILES[target]


def entries(target):
    try:
        raw = memory_path(target).read_text("utf-8-sig", "replace")
    except OSError:
        return []
    return [e.strip() for e in raw.split("§") if e.strip()]


def _save(target, items):
    p = memory_path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(SEP.join(items) + ("\n" if items else ""), "utf-8")
    tmp.replace(p)


def size(items):
    return len(SEP.join(items))


def apply(target, operations):
    """Add, patch or remove entries all at once; the size limit is checked on the result.
    Returns (ok, message, changes) where changes is a list of (action, text) for display."""
    if target not in LIMITS:
        return False, "target must be 'memory' (your notes) or 'user' (about the user)", []
    if isinstance(operations, dict):
        operations = [operations]
    items, changes = entries(target), []
    for op in operations or []:
        action = (op.get("action") or "").lower()
        content = (op.get("content") or op.get("new_text") or "").strip()
        old = (op.get("old_text") or "").strip()
        if action == "add":
            if not content:
                return False, "'add' needs content", []
            if "§" in content:
                content = content.replace("§", "-")
            if any(content.lower() == e.lower() for e in items):
                continue
            items.append(content)
            changes.append(("add", content))
        elif action in ("patch", "remove"):
            if not old:
                return False, f"'{action}' needs old_text (some text from the entry)", []
            hits = [i for i, e in enumerate(items) if old in e]
            if not hits:
                return False, f"No entry contains: {old[:80]}", []
            if len(hits) > 1:
                return False, f"More than one entry contains '{old[:60]}'. Quote more of it.", []
            i = hits[0]
            if action == "remove":
                changes.append(("remove", items.pop(i)))
            else:
                if not content:
                    return False, "'patch' needs content (the replacement text)", []
                items[i] = items[i].replace(old, content, 1)
                changes.append(("patch", items[i]))
        else:
            return False, f"Unknown action '{action}'. Use add, patch or remove.", []
    if size(items) > LIMITS[target]:
        listing = "\n".join(f"- {e}" for e in entries(target))
        return (False, f"That would make {MEMORY_FILES[target]} {size(items)} characters; the limit is "
                       f"{LIMITS[target]}. In ONE call, remove or shorten stale entries and add the new one. "
                       f"Current entries:\n{listing}", [])
    if changes:
        _save(target, items)
    return True, f"Saved. {MEMORY_FILES[target]} is {size(items)}/{LIMITS[target]} characters.", changes


def prompt_block(name):
    mem, user = entries("memory"), entries("user")
    parts = []
    if mem:
        parts.append("Your notes from earlier sessions:\n<memory>\n" + SEP.join(mem) + "\n</memory>")
    if user:
        parts.append(f"What you know about {name}:\n<user>\n" + SEP.join(user) + "\n</user>")
    return "\n\n".join(parts)


# ─────────────────────────── past sessions ───────────────────────────

def search_sessions(query, limit=5, skip=None):
    """Find earlier conversations mentioning every word of the query. Newest first."""
    words = [w.lower() for w in re.findall(r"\w[\w.\-/]*", query or "") if len(w) > 1]
    if not words:
        return []
    folder = engines.HOME / "sessions"
    hits = []
    for f in sorted(folder.glob("*.json"), reverse=True) if folder.exists() else []:
        if skip and Path(skip) == f:
            continue
        try:
            d = json.loads(f.read_text("utf-8-sig"))
        except (OSError, ValueError):
            continue
        msgs = [m.get("text") or "" for m in d.get("history", []) if m.get("text")]
        whole = (d.get("title", "") + "\n" + "\n".join(msgs)).lower()
        if not all(w in whole for w in words):
            continue  # every word must appear somewhere in the conversation
        scored = sorted(((sum(w in t.lower() for w in words), i) for i, t in enumerate(msgs)), reverse=True)
        snippets = []
        for n, i in scored[:2]:
            if not n:
                break
            text, low = msgs[i], msgs[i].lower()
            at = min((low.find(w) for w in words if w in low), default=0)
            a, b = max(0, at - 140), min(len(text), at + 220)
            snippets.append(("…" if a else "") + " ".join(text[a:b].split()) + ("…" if b < len(text) else ""))
        hits.append({"title": d.get("title") or "(untitled)", "folder": d.get("cwd", ""),
                     "when": time.strftime("%d %b %Y %H:%M", time.localtime(d.get("updated", 0))),
                     "matches": sum(1 for n, _ in scored if n), "snippets": snippets, "updated": d.get("updated", 0)})
    hits.sort(key=lambda h: h["updated"], reverse=True)
    return hits[:limit]
