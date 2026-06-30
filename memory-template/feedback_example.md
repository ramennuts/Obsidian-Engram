---
name: feedback_example
description: Keep diffs scoped — don't refactor unrelated code in the same change.
type: feedback
scope: core
---

Don't refactor or reformat unrelated code in a change that's about something else.

**Why:** it buries the real change in review noise and makes reverts risky.

**How to apply:** keep each PR to one concern. If you spot unrelated cleanup worth
doing, note it separately instead of folding it in. See [[user_example]].
