---
name: Bug report
about: Something isn't working as expected
title: "[bug] "
labels: bug
---

**What happened**
A clear description of the bug.

**Expected**
What you expected instead.

**Repro**
Steps to reproduce. If it's the hook or archiver, include the relevant slice of your
`build-queue.md` / handoff (redact anything sensitive).

**Environment**
- OS:
- Python version (`python3 --version`):
- Agent (Claude Code / other):
- `ENGRAM_VAULT` set? (`echo $ENGRAM_VAULT`):

**Doctor output**
```
$ ENGRAM_VAULT=... python3 scripts/doctor.py
```
