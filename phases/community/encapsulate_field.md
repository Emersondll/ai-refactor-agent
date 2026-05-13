# Community Skill — Encapsulate Field (Fowler)

Make public fields private and expose only necessary accessors.

## What you MUST do

- Identify fields declared as `public` (non-constant, non-static).
- Change them to `private`.
- Add a getter method if the field is read from outside the class.
- Add a setter method only if the field is written from outside the class.
- Getter naming: `getFieldName()` for objects, `isFieldName()` for booleans.

## What you MUST NOT do

- Do NOT encapsulate `public static final` constants — they are intentionally public.
- Do NOT add setters speculatively — only if there is evidence of external writes.
- Do NOT change fields annotated with `@JsonProperty` or `@SerializedName` — serialization frameworks access them directly.
