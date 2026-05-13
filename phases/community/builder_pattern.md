# Community Skill — Builder Pattern (GoF)

Introduce a Builder for classes with more than 4 constructor parameters.

## What you MUST do

- Identify classes with a constructor that has more than 4 parameters.
- Add a `public static Builder` nested class inside the same file.
- The Builder has one method per field (returning `this` for chaining) and a `build()` method.
- Keep the original constructor as-is (do NOT remove it) — the Builder calls it.

## What you MUST NOT do

- Do NOT remove the original constructor — callers in other files depend on it.
- Do NOT create a new file for the Builder.
- Do NOT apply if the class already has a Builder or uses Lombok `@Builder`.
