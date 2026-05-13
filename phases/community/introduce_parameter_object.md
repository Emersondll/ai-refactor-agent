# Community Skill — Introduce Parameter Object (Fowler)

Group related parameters that always appear together into a Java record.

## What you MUST do

- Identify methods with 4 or more parameters where a logical subset always appears together.
- Extract that subset into a `record` declared as a nested `record` inside the same file (do NOT create a new file).
- Update the method signature to accept the record instead of the individual parameters.
- Update all call sites WITHIN THE SAME FILE only.

## What you MUST NOT do

- Do NOT modify call sites in other files — that would break the build.
- Do NOT create new top-level classes or files.
- Do NOT apply if the method has fewer than 4 parameters.
