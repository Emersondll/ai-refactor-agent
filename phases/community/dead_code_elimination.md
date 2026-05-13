# Community Skill — Dead Code Elimination

Remove unused code that adds noise and maintenance burden.

## What you MUST do

- Remove private methods that are never called within the class.
- Remove unused private fields that are declared but never read.
- Remove unused local variables inside methods.
- Remove unused import statements.
- Remove commented-out code blocks (// old code that was disabled).

## What you MUST NOT do

- Do NOT remove public or protected members — callers in other files may use them.
- Do NOT remove fields annotated with `@Autowired`, `@Value`, `@Mock`, `@InjectMocks`.
- Do NOT remove methods annotated with `@Bean`, `@Override`, `@EventListener`.
- When in doubt, leave it — a false positive here breaks the build.
