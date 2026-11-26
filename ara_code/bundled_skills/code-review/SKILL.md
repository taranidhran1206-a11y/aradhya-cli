---
name: code-review
description: Use when asked to review code, a diff, a branch or a pull request for bugs and risks.
---

# Code review

1. Get the change: `git diff` (uncommitted), `git diff main...HEAD` (a branch), or the files named.
2. Read the surrounding code for each change, not just the diff lines. Check callers of anything whose
   signature or behaviour changed (grep for the name).
3. Look for, in this order:
   - **Bugs**: wrong conditions, off-by-one, null/None and empty cases, error paths that swallow failures,
     race conditions, resources not closed.
   - **Security**: secrets in code, injection (SQL, shell, HTML), missing auth checks, unsafe deserialization.
   - **Breaking changes**: APIs, file formats, config or database changes without migration.
   - **Tests**: does anything test the new behaviour? Would the tests catch the bug you're worried about?
   - Then, briefly, readability and simpler ways to do the same thing.
4. If you can, prove a suspected bug: run the tests, or a tiny script that shows it.

## Report
- Lead with the verdict in one line.
- List findings most serious first, each with `path:line`, what goes wrong, and a concrete fix.
- Say what you checked and found fine, in one line. Skip nitpicks unless asked.
- Don't edit the code unless the user asked you to fix things.
