---
name: java-dry-extraction
description: Use when multiple Java files contain repeated logic — identifies duplicated methods or blocks across service and utility classes and extracts them into shared utility classes.
---

# java-dry-extraction

## LLM INSTRUCTIONS

You are applying the **Don't Repeat Yourself (DRY)** principle across multiple Java files.

## Your task

1. Analyze the provided files for methods or code blocks that are **identical or near-identical** (same logic, possibly different variable names).
2. Decide: extract to a **new utility class** OR consolidate into one of the existing files.
3. Return the **complete updated content** of ALL affected files, plus any new utility class.

## Extraction rules

1. Only extract blocks of **≥ 5 lines** that appear in **2+ files** with the same logic.
2. The extracted method name MUST describe WHAT it does: `validateDocument`, `buildErrorResponse`, `parseAmount`.
3. New utility classes MUST follow this pattern:
   ```java
   public final class XyzUtils {
       private XyzUtils() {}
       public static ReturnType methodName(ParamType param) { ... }
   }
   ```
4. Place the new utility class in the **same package** as the files that use it (copy the `package` declaration from the first file).
5. The extracted method must be `public static` — utility classes have no state.
6. If the repeated code references instance fields, pass those values as method **parameters** instead.

## Do NOT extract

- `toString()`, `equals()`, `hashCode()` — standard Java methods
- `@Override` interface implementations — they have different semantic roles
- Simple getters and setters
- Constructors and factory methods
- Blocks that need more than **3 parameters** — too coupled to extract cleanly
- Code that references Spring context (`@Autowired`, `@Service`, application events)

## Output format

For **every file that changes** (including any NEW file), output exactly this format:

```
// FILE: FileName.java
```java
[complete file content]
```
```

Output ONLY changed files. Do NOT output files that were not modified.
Preserve ALL existing behavior — the result of every method call must be identical before and after extraction.
