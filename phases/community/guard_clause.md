# Community Skill — Guard Clause (Clean Code)

Replace nested conditionals with early returns to reduce nesting depth.

## What you MUST do

- Identify methods with if/else blocks nested more than 2 levels deep.
- Invert the condition at each nesting level and return (or throw) early.
- The "happy path" should be the last non-guarded code in the method.
- Example transformation:
  BEFORE: `if (valid) { if (hasBalance) { process(); } }`
  AFTER: `if (!valid) return; if (!hasBalance) return; process();`

## What you MUST NOT do

- Do NOT change method signatures or return types.
- Do NOT introduce new exception types not already used in the file.
- Do NOT apply if the method already has max 2 nesting levels — return unchanged.
