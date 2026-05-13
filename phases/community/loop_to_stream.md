# Community Skill — Loop to Stream (Effective Java)

Replace imperative for/while loops with Stream API equivalents.

## What you MUST do

- Identify simple loops that: filter elements, map/transform elements, or collect into a list/set.
- Replace with `stream().filter().map().collect(Collectors.toList())` equivalents.
- Add `import java.util.stream.Collectors;` if not already present.

## What you MUST NOT do

- Do NOT convert loops that modify external state (side effects) — streams are not appropriate there.
- Do NOT convert loops with `break` or `continue` unless the logic maps cleanly to `filter()`.
- Do NOT convert loops that catch checked exceptions inside the body.
- Do NOT apply if the result is less readable than the original loop.
