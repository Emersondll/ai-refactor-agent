---
name: java-refactor-context
description: Use when refactoring Java source files — provides compact LLM instructions for applying Clean Code, SOLID, and architecture rules without changing behavior or adding features.
---

# Java Refactor Context

## LLM INSTRUCTIONS

Refactor the Java file below applying ONLY the rules listed in PHASE RULES.
Preserve all existing behavior — do NOT add features, change method signatures, or modify tests.
Apply DRY, KISS, early return, and max 3 nesting levels where relevant.
Prefer small, focused changes over large rewrites.

## Refactor Rules

**MUST preserve:** package declaration, class-level annotations, public method signatures, existing tests.  
**MUST NOT:** add new dependencies, create new classes, use System.out, ignore exceptions silently.  
**COMPLEXITY:** methods ≤ 30 lines, nesting ≤ 3 levels, cyclomatic complexity ≤ 10.  
**NAMING:** self-explanatory names — no abbreviations, no generic names (data, info, temp).  
**SOLID:** one responsibility per class/method; depend on abstractions, not implementations.

## Pipeline Documentation

Loaded by `java/refactor.py → _refactor_whole_file()` and `_refactor_by_method()` when `mode="refactor"`.
Section `## LLM INSTRUCTIONS` injected into `_build_task(mode="refactor")` as base rules.
Section `## Refactor Rules` appended to phase_delta for targeted guidance.

Token saving: replaces hardcoded refactor hints (~180 tokens) with a reusable, version-controlled skill.
Integration point: `main.py` or `agent/loop.py` — load before calling `refactor_file()`.
