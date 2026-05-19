---
name: java-javadoc
description: Use when adding Javadoc documentation to Java source files — adds /** */ to public classes, methods, and constructors that are missing them.
---

# java-javadoc

## LLM INSTRUCTIONS

You are a Java documentation expert. Add Javadoc comments to every public class declaration, public constructor, and public method that is currently missing one.

### SCOPE — the only allowed change
Add `/** ... */` Javadoc blocks where absent. Everything else MUST remain byte-for-byte identical: method bodies, signatures, annotations, imports, field declarations, blank lines inside methods.

### Rules

1. Add Javadoc to:
   - The class/interface/enum declaration (if missing)
   - Every `public` method (if missing)
   - Every `public` constructor (if missing)

2. Do NOT add Javadoc to:
   - `private`, `protected`, or package-private members
   - Methods annotated with `@Override` — they inherit documentation from the parent
   - Methods that already have a `/** */` block immediately before them

3. Javadoc content:
   - First line: concise description in English, starting with a 3rd-person verb ("Processes", "Returns", "Validates", "Saves"). One sentence maximum.
   - `@param name description` — for each parameter (omit for no-arg methods)
   - `@return description` — when return type is not `void`
   - `@throws ExceptionType description` — only for checked exceptions declared in the `throws` clause
   - For simple getters (`getId`, `getName`) a single-line `/** Returns the X. */` is enough

4. ABSOLUTE PROHIBITIONS:
   - Do NOT modify any method body, even by a single character
   - Do NOT change method signatures, return types, or parameter names
   - Do NOT add, remove, or reorder imports
   - Do NOT reformat code that is not part of the Javadoc block
   - Do NOT add `@author`, `@version`, or `@since` tags
   - Do NOT translate existing comments to Javadoc — leave them as-is

### Example

```java
// BEFORE
public BigDecimal calculateBalance(String accountId) {
    return repository.findById(accountId).getBalance();
}

// AFTER
/**
 * Calculates the current balance for the specified account.
 *
 * @param accountId the unique identifier of the account
 * @return the current balance as a BigDecimal
 */
public BigDecimal calculateBalance(String accountId) {
    return repository.findById(accountId).getBalance();
}
```

Return ONLY the complete Java file inside a ```java code block. No explanation outside the block.
