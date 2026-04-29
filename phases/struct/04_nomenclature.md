# Phase 04 — Nomenclature

Rename identifiers that violate Java naming conventions.

## What you MUST do

- Rename any variable, field, or parameter that uses an abbreviation.
  `acnt` → `account`, `amt` → `amount`, `svc` → `service`, `repo` → `repository`
- Rename boolean variables and methods to start with `is`, `has`, `can`, or `should`.
  `active` → `isActive`, `valid` → `isValid`, `check()` → `isValid()`
- Rename methods with vague names to use a strong verb-noun pair.
  `process()` → `processTransaction()`, `get()` → `findById()`
- Rename constants that are not in UPPER_SNAKE_CASE.
- Update every usage of the renamed identifier within this file.
- Do NOT rename: public API methods, fields annotated with `@JsonProperty`,
  Spring beans annotated with `@Autowired`, `@Value`, or `@Qualifier`.
- Do NOT rename identifiers in other files — that is handled by phase 06.