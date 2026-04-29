# Phase 02 — Skill Imutabilidade (Final Keywords)

Esta é uma SKILL MANDATÓRIA. O código só será aceito se seguir estas regras rigidamente.

## Requisitos Indispensáveis:

- ADICIONE `final` a todos os parâmetros de método (ex: `public void foo(final String bar)`).
- ADICIONE `final` a todas as variáveis locais que são inicializadas e nunca reatribuídas.
- ADICIONE `final` a todos os campos (fields) que são inicializados no construtor e não possuem setters.
- NÃO ADICIONE `final` em campos anotados com `@Autowired` (a menos que seja injeção via construtor).
- NÃO ADICIONE `final` em classes/métodos em beans Spring que exigem Proxy CGLIB (ex: `@Transactional` em métodos).

**ATENÇÃO:** Se o parâmetro não possuir `final`, a refatoração será considerada FALHA.