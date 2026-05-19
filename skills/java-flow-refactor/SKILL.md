---
name: java-flow-refactor
description: Use when refactoring Java files that belong to an HTTP endpoint flow chain (controller → service → repository) — applies quality improvements while preserving the complete chain contract.
---

# java-flow-refactor

## LLM INSTRUCTIONS

You are refactoring a Java file that is part of an HTTP endpoint flow.

Your prompt includes:
- **ENDPOINT FLOW CONTEXT**: which endpoint(s) this file serves and the call chain
- **FILES IN THIS FLOW**: all files in the chain (controller, service impl, repository)
- **FLOW SIGNATURES**: method signatures of all related files
- **DEPENDENCY CONTEXT**: imported class signatures

## Rules by layer

### Controller (@RestController)
1. Keep ONLY: `@XxxMapping`, parameter binding (`@PathVariable`, `@RequestBody`, `@RequestParam`), ONE service call per endpoint, returning `ResponseEntity`.
2. Move ALL business logic (if/else chains, loops, calculations) into the service call delegation.
3. Do NOT remove `@Valid`, `@NotNull`, or any validation annotations from parameters.
4. Do NOT change URL paths, HTTP methods, or response status codes.

### Service Implementation
5. Apply guard clauses: methods with nested `if` depth ≥ 3 → use early return pattern.
6. Extract methods > 30 lines into descriptive `private` helpers.
7. Preserve the interface contract exactly — do NOT change any method signature declared in the interface.
8. Do NOT call repository methods not already present. Do NOT add new repository dependencies.

### Repository (interface)
9. Do NOT add business logic or new query methods. Leave the interface as is unless there is a clear naming convention violation.

## Shared file rules
10. If the file is marked **[SHARED]** in the flow context, it is used by multiple endpoints simultaneously. Be conservative: only refactor what is unambiguously safe for ALL listed flows.
11. Never change a method signature of a shared file — other flows depend on the current contract.

## General rules
12. Preserve ALL existing behavior — tests must pass after this refactoring.
13. Do NOT add imports for classes not present in DEPENDENCY CONTEXT or already in the file.
14. Do NOT invent interfaces or utility classes that do not exist in the project.
15. If the file already follows all rules above, return it UNCHANGED.

Return ONLY the complete refactored Java file inside a ```java block. No explanation outside the block.
