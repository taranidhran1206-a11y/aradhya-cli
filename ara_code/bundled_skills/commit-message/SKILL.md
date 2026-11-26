---
name: commit-message
description: Use when asked to commit, or to write a commit message for the current changes.
---

# Commit messages

1. Look first: `git status`, then `git diff --staged` (or `git diff` if nothing is staged). Read every change;
   don't guess from file names.
2. If nothing is staged, ask whether to stage everything or only some files. Never stage `.env`, keys or other
   secrets; warn if you see them.
3. Match the repo's style: check `git log --oneline -10`. If it uses prefixes like `feat:` or `fix:`, use them.
4. Write the message:
   - Subject: imperative mood ("Add", not "Added"), under 60 characters, no full stop.
   - Blank line, then a short body saying *why* the change was needed and anything surprising. Wrap near 72.
   - Group unrelated changes into separate commits when they're clearly separate.
5. Only run `git commit` if the user asked you to commit. Never push unless asked.

## Pitfalls
- Use `git commit -F <file>` or a heredoc for multi-line messages; `-m` with newlines breaks on Windows.
- Don't mention files the diff doesn't touch, and don't claim tests pass unless you ran them.
