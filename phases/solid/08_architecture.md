# Phase 08 — Layered Architecture

Enforce Spring layered architecture rules. Make concrete changes.

## What you MUST do

### Controller layer
- Move any business logic from `@RestController` / `@Controller` methods to the service.
- A controller method must only: validate input → call service → return response.
- Remove any direct `@Repository` call from a controller — route through a service.

### Service layer
- Add `@Transactional` to every service method that writes to the database.
- Remove `@Transactional` from controller methods.
- Replace field-level `@Autowired` with constructor injection + `private final`.

### Repository layer
- Move any business logic found inside a `@Repository` to the service layer.

### DTO boundary
- If a controller returns a `@Document` or `@Entity` directly,
  add `// TODO: wrap in a DTO` above the return statement.
- If a controller receives a `@Document` or `@Entity` as `@RequestBody`,
  add `// TODO: use a request model` above the parameter.

Do not change method signatures, return types, or existing test code.