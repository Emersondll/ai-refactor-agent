# Phase 03 — Inline Comments

Add inline comments explaining the WHY behind non-obvious logic.

## What you MUST do

- Add a `//` comment above every complex condition, non-trivial algorithm, or workaround.
- Comments must explain WHY the code does something, not WHAT it does.
  BAD:  `i++; // increment i`
  GOOD: `// Skip null entries to avoid NullPointerException downstream`
- Add `// TODO:` where you identify known limitations or missing validations.
- Remove commented-out code blocks (old implementations left in comments).
- Do not alter any existing code or logic.