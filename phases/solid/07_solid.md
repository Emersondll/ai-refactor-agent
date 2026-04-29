# Phase 07 — SOLID Principles

Apply SOLID principles. You MUST make concrete code changes, not just add comments.

## What you MUST do

### Single Responsibility (SRP)
- If the class mixes concerns (e.g. business logic + persistence + notifications),
  extract the secondary concern into a private method with a clear name.
- Do not create new classes — use private methods within the existing file.

### Dependency Inversion (DIP)
- Replace every `new ConcreteClass()` instantiation with a constructor-injected dependency.
- Replace every field-level `@Autowired` with constructor injection + `private final`.

  BEFORE:
  ```java
  @Autowired
  private PaymentRepository repo;
  ```
  AFTER:
  ```java
  private final PaymentRepository repo;

  public PaymentService(PaymentRepository repo) {
      this.repo = repo;
  }
  ```

### Open/Closed (OCP)
- Replace `instanceof` chains that select behavior with a method call on the object.
- Add `// TODO: consider strategy pattern` where adding a new type forces modifying this class.

### Liskov Substitution (LSP)
- Remove overrides that throw `UnsupportedOperationException` without reason.

### Interface Segregation (ISP)
- Add `// TODO: split interface` where the class implements an interface
  but leaves methods empty or throwing.

Do not change public API or method signatures.