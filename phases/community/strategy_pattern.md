# Community Skill — Strategy Pattern (GoF)

Replace type-based if/switch dispatch with Strategy interface.

## What you MUST do

- Identify methods that switch on a type field or enum to select behavior.
- Extract the varying behavior into a private interface (nested inside the same file).
- Create private static implementations (one per case) as anonymous classes or lambdas.
- Replace the if/switch with a Map lookup from type → strategy.

## What you MUST NOT do

- Do NOT create new top-level interfaces or classes — keep everything in the same file.
- Do NOT apply if there are only 2 cases — a simple if/else is more readable.
- Do NOT change the public method signature.
