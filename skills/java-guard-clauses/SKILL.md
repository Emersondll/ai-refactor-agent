---
name: java-guard-clauses
description: Use when refactoring Java methods that have deeply nested if-else blocks — applies early return pattern to reduce nesting depth and improve readability.
---

# java-guard-clauses

## LLM INSTRUCTIONS

You are a Java refactoring expert. Refactor the provided Java file applying the **Guard Clause** pattern.

### Target
Methods with 3 or more levels of nested `if` blocks.

### Rules
1. Identify deeply nested if-else chains in each method.
2. Invert the outer condition and return/throw early, eliminating one nesting level at a time.
3. Preserve ALL existing behavior — the refactoring must be semantically equivalent.
4. Do NOT change method signatures, access modifiers, or return types.
5. Do NOT add, remove, or reorder imports.
6. Do NOT touch methods that are already flat (nesting depth < 3).
7. If the method returns a value, every early return must return the correct type or throw.
8. Keep the "happy path" as the last statement after all guard checks.
9. For void methods, use `return;` as the early exit.
10. Do NOT combine multiple guard conditions into one — one condition per guard clause.

### Example

Before:
```java
public String process(Order order) {
    if (order != null) {
        if (order.isActive()) {
            if (order.hasItems()) {
                return calculate(order);
            } else {
                return "EMPTY";
            }
        }
    }
    return null;
}
```

After:
```java
public String process(Order order) {
    if (order == null) return null;
    if (!order.isActive()) return null;
    if (!order.hasItems()) return "EMPTY";
    return calculate(order);
}
```

Return ONLY the complete refactored Java file inside a ```java code block. No explanation outside the block.
