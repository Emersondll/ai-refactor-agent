# Community Skill — Record Migration (Java 16+)

Replace simple data-holder classes with Java records.

## What you MUST do

- Identify classes that: have only final private fields, a constructor that sets all fields, and only getters (no setters, no business logic).
- Convert them to `record` syntax: `public record ClassName(Type field1, Type field2) {}`.
- Records auto-generate constructor, getters (`field1()` not `getField1()`), `equals`, `hashCode`, `toString`.
- Update getter call sites WITHIN THE SAME FILE from `getField()` to `field()`.

## What you MUST NOT do

- Do NOT convert classes annotated with `@Entity`, `@Document`, `@Table` — JPA/MongoDB require mutable classes.
- Do NOT convert classes that have mutable state (non-final fields, setters).
- Do NOT convert classes with inheritance (`extends` something other than `Object`).
- Do NOT update getter call sites in other files — that would break callers.
