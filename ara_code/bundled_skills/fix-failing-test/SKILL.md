---
name: fix-failing-test
description: Use when a test, build or CI check is failing and needs to be fixed.
---

# Fixing a failing test

1. **Reproduce it first.** Run only the failing test (e.g. `pytest path::test_name -x`, `npm test -- -t "name"`,
   `./gradlew test --tests Name`). If you can't reproduce it, say so before changing anything.
2. **Read the whole error**, from the bottom of the traceback up to the first line in this project's code.
3. **Decide what's wrong: the code or the test.** Read the test's intent and recent changes
   (`git log -p -3 -- <file>`). Don't edit a test just to make it pass unless the test itself is wrong, and say
   so when you do.
4. **Make the smallest fix** that addresses the cause, not the symptom. No sleeps or retries to hide timing bugs.
5. **Verify**: run the failing test, then the whole suite (or the module's tests) to check nothing else broke.
6. Report the cause in one or two sentences, the fix, and the test results.

## Pitfalls
- Flaky tests: run it 3-5 times before and after; look for shared state, time, randomness, order dependence.
- "Works locally, fails in CI": compare versions, environment variables, timezone, file paths and case
  sensitivity.
- If the fix needs a dependency upgrade or a large refactor, stop and ask first.
