# Phase 12 — Integration Tests

Generate a Spring Boot integration test. You MUST generate real, compilable test code.

## For REST Controllers

```java
@SpringBootTest
@AutoConfigureMockMvc
class <ClassName>IT {

    @Autowired
    MockMvc mockMvc;

    @BeforeEach
    void setUp() { /* insert test data */ }

    @AfterEach
    void tearDown() { /* clean test data */ }

    @Test
    void test<Endpoint>Returns200() throws Exception {
        mockMvc.perform(post("/endpoint")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"field\":\"value\"}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.field").value("expected"));
    }

    @Test
    void test<Endpoint>Returns400WhenInputInvalid() throws Exception {
        mockMvc.perform(post("/endpoint")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
            .andExpect(status().isBadRequest());
    }
}
```

## For Services

```java
@SpringBootTest
class <ClassName>IT {

    @Autowired
    ServiceUnderTest service;

    @Autowired
    RepositoryName repository;

    @BeforeEach
    void setUp() { repository.deleteAll(); }

    @Test
    void test<Method>PersistsCorrectly() {
        // Arrange: insert data
        // Act: call service
        // Assert: verify database state
    }
}
```

## Coverage REQUIRED

- 200 OK — successful operation
- 400 Bad Request — invalid input (controllers only)
- 404 Not Found — missing resource
- Concurrent or transactional behavior where applicable

## Rules

- Do NOT use `@MockBean` for internal Spring beans
- Each test must be independent and runnable in any order
- Use `@BeforeEach` to set up and `@AfterEach` to clean data