---
name: java-solid-dip
description: Use when refactoring Java classes that hardcode concrete service, repository, or manager instantiation — applies Dependency Inversion Principle via constructor injection.
---

# java-solid-dip

## LLM INSTRUCTIONS

You are a Java refactoring expert applying the **Dependency Inversion Principle (DIP)**.

### Target
Classes that instantiate dependencies directly: `new ConcreteService()`, `new ConcreteRepository()`, `new SomeManager()` inside constructors or field initializers.

### SCOPE — the ONE allowed change
The **only** transformation permitted is: replace `new ConcreteClass()` with a constructor-injected field.
Everything else in the file MUST be returned exactly as received.

### Rules
1. Identify `new ConcreteClass()` calls where the class is a service, repository, manager, handler, processor, or impl.
2. Replace with a constructor parameter of the correct type.
3. Store the injected dependency as a `private final` field.
4. Check the DEPENDENCY CONTEXT — if an interface for that class exists, use the interface type, NOT the concrete class.
5. If NO interface exists in the dep_context, inject the concrete class directly. Do NOT invent interfaces.
6. Add `@Autowired` on the constructor if the class uses Spring annotations (`@Service`, `@Component`, `@RestController`, `@Repository`).
7. If the class already uses `@Autowired` field injection (not constructor), add a new `@Autowired` field for the new dependency.
8. Remove the `new ConcreteClass()` instantiation entirely — use the injected field.
9. Do NOT change public method signatures or remove existing constructor parameters.
10. Do NOT add imports for classes not present in the DEPENDENCY CONTEXT or already imported.
11. If the class is a `record`, do NOT apply DIP — records use canonical constructors, skip this file.

### ABSOLUTE PROHIBITIONS — violating any of these will break the build
- **NEVER create interfaces** that do not already exist in the project. Rule 5 is mandatory.
- **NEVER rename any method**, parameter, field, or class.
- **NEVER change any method signature** — not return type, not parameter types, not parameter names, not throws clause.
- **NEVER move, reorder, or restructure methods** within the class.
- **NEVER add business logic**, conditions, loops, or new method calls.
- **NEVER remove annotations** (`@Override`, `@Transactional`, `@Cacheable`, etc.).
- **NEVER add imports** beyond what is required for the newly injected field.
- **NEVER modify exception handling** blocks.
- If there is no `new ConcreteClass()` to replace, return the file unchanged.

Return ONLY the complete refactored Java file inside a ```java code block. No explanation outside the block.
