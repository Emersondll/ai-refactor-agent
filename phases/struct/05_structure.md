# Phase 05 — Code Structure

Reorganize the internal structure of the class for clarity.

## What you MUST do

Reorder members in this exact sequence:
  1. Static constants and static fields
  2. Instance fields
  3. Constructors
  4. Public methods
  5. Protected methods
  6. Private methods

- Replace field-level `@Autowired` injection with constructor injection.
  BEFORE: `@Autowired private UserService userService;`
  AFTER:  constructor with `this.userService = userService;`
- Add `private final` to every injected field after converting to constructor injection.
- Extract any block of code repeated more than once into a named private method.
- Replace `if (x == null) { ... } else { ... }` patterns with early return guard clauses.
- Replace `optional.get()` without `isPresent()` check with `optional.orElseThrow()`.
- Do not change business logic, only structure and organization.