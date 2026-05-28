from ai.prompt import build_prompt, BASE_CONSTRAINTS


def test_base_constraints_is_string():
    assert isinstance(BASE_CONSTRAINTS, str)
    assert len(BASE_CONSTRAINTS) > 0

def test_base_constraints_in_every_prompt():
    prompt = build_prompt("public class A {}", "# Rule\n- Do X", "refactor", "A.java")
    assert "PRESERVE the package declaration" in prompt
    assert "TECHNICAL CONSTRAINTS" in prompt

def test_no_java_example_block_in_prompt():
    prompt = build_prompt("public class A {}", "# Rule\n- Do X", "refactor", "A.java")
    count = prompt.count("```java")
    assert count == 1, f"Expected 1 java block (source), but found {count}"

def test_phase_delta_appears_in_prompt():
    prompt = build_prompt("public class A {}", "# SOLID\n- Apply DIP", "refactor", "A.java")
    assert "Apply DIP" in prompt

def test_dep_context_included_when_provided():
    dep = "// SUGGESTED IMPORT: import com.ex.Service;\n// Class: com.ex.Service"
    prompt = build_prompt("public class A {}", "# Rule", "refactor", "A.java", dep_context=dep)
    assert "DEPENDENCY CONTEXT" in prompt
    assert "SUGGESTED IMPORT" in prompt

def test_dep_context_absent_when_empty():
    prompt = build_prompt("public class A {}", "# Rule", "refactor", "A.java", dep_context="")
    assert "DEPENDENCY CONTEXT" not in prompt

def test_test_mode_task_different_from_refactor():
    p_refactor = build_prompt("public class A {}", "# Rule", "refactor", "A.java")
    p_test = build_prompt("public class A {}", "# Rule", "test", "A.java")
    assert "JUnit" in p_test or "unit test" in p_test.lower()
    assert p_refactor != p_test

def test_source_file_appears_at_end():
    code = "public class MyClass { }"
    prompt = build_prompt(code, "# Rule", "refactor", "MyClass.java")
    assert prompt.endswith("```") or code in prompt
    assert prompt.index("SOURCE FILE") > prompt.index("PHASE RULES")
