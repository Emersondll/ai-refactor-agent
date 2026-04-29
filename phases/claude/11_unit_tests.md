# Phase 11 — Unit Tests

Generate a COMPLETE JUnit 5 + Mockito unit test class. You MUST generate real test code.

## Structure

```java
@ExtendWith(MockitoExtension.class)
class <ClassName>Test {

    @Mock
    DependencyA mockA;

    @Mock
    DependencyB mockB;

    @InjectMocks
    ClassName underTest;

    @Test
    void test<Method><Scenario>() {
        // Arrange
        when(mockA.method()).thenReturn(value);

        // Act
        ResultType result = underTest.methodUnderTest(input);

        // Assert
        assertEquals(expected, result);
        verify(mockA).method();
    }
}
```

## Coverage REQUIRED

For every public method, you MUST write:
1. Happy path — normal successful execution
2. Edge case — null input, empty list, zero value, or boundary condition
3. Failure path — dependency throws exception, returns empty Optional, or returns null

For methods with `if/else` or `switch`, write one test per branch.

## Rules

- Use `@ExtendWith(MockitoExtension.class)` — NOT `@SpringBootTest`
- Use `@Mock` for every constructor dependency
- Use `@InjectMocks` for the class under test
- Use `when(...).thenReturn(...)` for stubbing
- Use `assertThrows(ExceptionType.class, () -> ...)` for exception tests
- Use `verify(mock).method()` to confirm interactions
- Extract repeated values to `private static final` constants at the top
- Do NOT connect to any database, file system, or external service
- Do NOT test private methods directly
- Return ONLY the complete test file — no explanations