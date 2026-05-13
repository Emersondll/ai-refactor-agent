# Community Skill — Replace Magic Number (Fowler)

Replace inline numeric or string literals with named constants.

## What you MUST do

- Identify numeric or string literals that appear more than once OR whose meaning is not self-evident.
- Declare them as `private static final` constants at the top of the class, before constructors.
- Name constants in UPPER_SNAKE_CASE that express the business meaning (e.g. `MAX_RETRY_ATTEMPTS`, `DEFAULT_TIMEOUT_SECONDS`).
- Replace all occurrences of the literal with the constant name.

## What you MUST NOT do

- Do NOT extract `0`, `1`, `-1`, `true`, `false` — these are universally understood.
- Do NOT extract literals that only appear once AND are self-evident in context.
- Do NOT change method signatures or class structure.
