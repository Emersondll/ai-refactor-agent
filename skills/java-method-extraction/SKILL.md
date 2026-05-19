---
name: java-method-extraction
description: Use when refactoring Java files with methods longer than 30 lines — extracts cohesive sub-blocks into named private helper methods following Clean Code principles.
---

# java-method-extraction

## LLM INSTRUCTIONS

You are a Java refactoring expert. Refactor the provided Java file applying **Method Extraction**.

### Target
Methods with more than 30 lines of code.

### Rules
1. Identify the largest self-contained sub-block inside a long method.
2. Extract it into a `private` helper method with a name that describes WHAT it does (verb + noun: `validatePayment`, `buildResponse`, `calculateTotal`).
3. Pass ONLY the variables the extracted method needs as parameters.
4. The return type must match what the caller needs — use the same types already in scope.
5. Preserve ALL existing behavior — results must be identical.
6. Do NOT change public or protected method signatures.
7. Do NOT extract blocks of fewer than 5 lines — not worth the overhead.
8. Do NOT extract a block that references too many local variables (more than 3 inputs = too coupled, leave it).
9. Place extracted methods directly below the method they were extracted from.
10. After extraction, the original method body should read like a high-level summary of steps.

### Signs of a good extraction target
- A comment describes what the block does ("// validate request")
- The block has a clear input and a clear output
- The block is at a different level of abstraction from the rest of the method

### Signs of a bad extraction target
- The block needs 4+ parameters
- The block is already only 3 lines
- Extracting it makes the caller LESS readable

Return ONLY the complete refactored Java file inside a ```java code block. No explanation outside the block.
