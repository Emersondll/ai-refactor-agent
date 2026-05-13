# Community Skill — Null to Optional (Effective Java)

Replace nullable return values with Optional<T>.

## What you MUST do

- Identify private or package-private methods that return a reference type and may return `null`.
- Change the return type from `T` to `Optional<T>`.
- Replace `return null` with `return Optional.empty()`.
- Wrap non-null returns: `return Optional.of(value)` or `return Optional.ofNullable(value)`.
- Update all call sites WITHIN THE SAME FILE to use `.orElse()`, `.orElseThrow()`, or `.isPresent()`.
- Add `import java.util.Optional;` if not already present.

## What you MUST NOT do

- Do NOT change PUBLIC method signatures — Optional on public APIs is controversial and may break callers.
- Do NOT apply to methods that return collections (use empty collection instead).
- Do NOT wrap primitives — use `OptionalInt`, `OptionalLong` only if already used in the file.
