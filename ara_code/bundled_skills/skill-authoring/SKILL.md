---
name: skill-authoring
description: Use when writing or improving a skill, including after /learn or a hard task worth remembering.
---

# Writing a good skill

A skill is a playbook future-you follows without re-deriving anything. Only the name and description are seen
up front, so the description decides whether the skill ever gets used.

## Frontmatter
- `name`: lowercase-with-hyphens, names the job ("deploy-to-ec2"), not the project or date.
- `description`: one sentence, under 160 characters, starting "Use when …". Say when it applies, not how it
  works. No "powerful", "comprehensive" or other filler.

## Body
1. **When to use it**: one or two lines, including when *not* to.
2. **Steps**: numbered, with the exact commands that worked. Use placeholders like `<branch>` for things that
   change.
3. **Pitfalls**: each one as a rule plus why ("Run migrations before seeding: the seed script needs the new
   columns").
4. **Check**: how to tell it worked.

## Rules
- Write lessons, not a log. No dates, ticket numbers or "today we…".
- One skill per job. If one already covers it, patch that one instead of adding another.
- Keep SKILL.md under ~150 lines. Put long references in `references/<topic>.md` and point to them.
- Never put secrets, tokens or personal data in a skill.
- When a skill turns out wrong or incomplete while you use it, fix it right then with a patch.
