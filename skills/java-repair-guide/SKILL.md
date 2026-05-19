---
name: java-repair-guide
description: Use when a Java refactoring or test generation cycle produces code that fails validation — guides the repair prompt to be minimal, targeted, and token-efficient.
---

# Java Repair Guide

## LLM INSTRUCTIONS

Fix ONLY the specific error reported below. Do NOT rewrite the whole file.
Preserve all business logic, method signatures, and class-level annotations.
Do NOT add or remove imports beyond what the error requires.
Do NOT change test behavior — fix only the compilation or execution error.

## Repair Rules by Error Type

**ENUM/VARIABLE ERROR** — replace the wrong value with one from ALLOWED ENUM VALUES only.  
**RECORD CONSTRUCTOR** — use ALL declared fields in the canonical constructor order from DEPENDENCY CONTEXT.  
**METHOD ERROR** — check DEPENDENCY CONTEXT for the real method signature; remove the wrong call.  
**IMPORT ERROR** — add the missing import using the exact package from DEPENDENCY CONTEXT.  
**TYPE MISMATCH** — align mock return type with the exact return type in DEPENDENCY CONTEXT.  
**SPRING CONTEXT ERROR** — remove @SpringBootTest/@WebMvcTest; use @ExtendWith(MockitoExtension.class) + @InjectMocks + @Mock.  
**NULLPOINTEREXCEPTION** — add Mockito.when(mock.method(...)).thenReturn(...) before the method call.

## Pipeline Documentation

Loaded by `java/refactor.py → _generate_and_validate()` repair loop for refactoring mode.
Loaded by `java/refactor.py → generate_tests()` repair loop for test generation mode.

Section `## LLM INSTRUCTIONS` is injected into the repair prompt as `error_reason` prefix.
Section `## Repair Rules by Error Type` is injected only for build-fail repairs.

Token saving: replaces verbose Python error strings (~200 tokens) with targeted skill section (~80 tokens).
