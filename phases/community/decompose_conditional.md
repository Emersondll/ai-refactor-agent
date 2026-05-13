# Community Skill — Decompose Conditional (Fowler)

Extract complex boolean conditions into named predicate methods.

## What you MUST do

- Identify `if` conditions that have more than 2 clauses joined by `&&` or `||`.
- Extract the condition into a private method with a name that describes what it checks (e.g. `isEligibleForDiscount()`).
- The predicate method returns `boolean` and takes the same parameters the condition uses.

## What you MUST NOT do

- Do NOT decompose simple single-clause conditions.
- Do NOT change the observable behavior of the conditional logic.
- Do NOT create new classes.
