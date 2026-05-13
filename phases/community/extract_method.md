# Community Skill — Extract Method (Fowler)

Break long methods into smaller, named sub-methods.

## What you MUST do

- If a method has more than 20 lines, identify logical blocks inside it and extract each into a private method with a descriptive name.
- The extracted method name must describe WHAT it does, not HOW (e.g. `validateTransaction()` not `doCheck()`).
- The original method becomes an orchestration of the extracted methods.
- Do NOT change the public signature of the original method.
- Do NOT extract if the method is already ≤ 20 lines — return the file unchanged.

## What you MUST NOT do

- Do NOT create new classes.
- Do NOT change method visibility (private stays private, public stays public).
- Do NOT extract a block that references more than 3 local variables — it would require too many parameters.
