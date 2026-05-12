# Phase 09 — Design Patterns

Apply design patterns where they reduce duplication or complexity. Make real code changes.

## What you MUST do

### Factory method
- If the class creates instances of 2+ different types based on a condition,
  extract the creation logic into a private method named `create*` or `build*`.

### Template method
- If two methods share identical steps with one small variation,
  extract the shared skeleton into a private method and pass the variation as a lambda or parameter.

### Null Object / Optional
- Replace every `return null` in a method whose return type should be `Optional<T>`
  with `return Optional.empty()`.
- Replace every null check `if (x != null)` on an Optional value
  with `x.ifPresent(...)` or `x.map(...).orElse(...)`.

### DRY
- If the same expression is evaluated in more than one place,
  assign it to a named local variable and reuse.
- If the same block of code appears in more than one method,
  extract it into a private method and call it from both places.

