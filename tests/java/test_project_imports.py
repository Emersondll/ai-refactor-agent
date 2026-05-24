import pytest
import tempfile
import os
from java.refactor import build_project_imports, _auto_inject_missing_imports


def _make_project(tmp_path, files: dict):
    """Create a fake src/main/java tree from a dict {rel_path: source_code}."""
    main_java = os.path.join(tmp_path, "src", "main", "java")
    os.makedirs(main_java, exist_ok=True)
    for rel, src in files.items():
        full = os.path.join(main_java, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(src)


def test_scans_classes_enums_records(tmp_path):
    _make_project(str(tmp_path), {
        "com/x/Foo.java": "package com.x;\npublic class Foo {}",
        "com/x/Bar.java": "package com.x;\npublic enum Bar { A, B }",
        "com/x/Baz.java": "package com.x;\npublic interface Baz {}",
        "com/y/Tx.java": "package com.y;\npublic record Tx(String id) {}",
    })
    m = build_project_imports(str(tmp_path))
    assert m["Foo"] == "import com.x.Foo;"
    assert m["Bar"] == "import com.x.Bar;"
    assert m["Baz"] == "import com.x.Baz;"
    assert m["Tx"] == "import com.y.Tx;"


def test_ignores_test_sources(tmp_path):
    main_java = os.path.join(str(tmp_path), "src", "main", "java", "com", "x")
    test_java = os.path.join(str(tmp_path), "src", "test", "java", "com", "x")
    os.makedirs(main_java, exist_ok=True)
    os.makedirs(test_java, exist_ok=True)
    with open(os.path.join(main_java, "Real.java"), "w") as f:
        f.write("package com.x;\npublic class Real {}")
    with open(os.path.join(test_java, "RealTest.java"), "w") as f:
        f.write("package com.x;\npublic class RealTest {}")
    m = build_project_imports(str(tmp_path))
    assert "Real" in m
    assert "RealTest" not in m


def test_ignores_non_public_classes(tmp_path):
    _make_project(str(tmp_path), {
        "com/x/Private.java": "package com.x;\nclass Private {}",  # no 'public'
        "com/x/Public.java": "package com.x;\npublic class Public {}",
    })
    m = build_project_imports(str(tmp_path))
    assert "Public" in m
    # package-private class not exported via map (conservative)
    assert "Private" not in m


def test_handles_classes_with_modifiers(tmp_path):
    _make_project(str(tmp_path), {
        "com/x/Sealed.java": "package com.x;\npublic final class Sealed {}",
        "com/x/Abs.java":    "package com.x;\npublic abstract class Abs {}",
    })
    m = build_project_imports(str(tmp_path))
    assert m["Sealed"] == "import com.x.Sealed;"
    assert m["Abs"] == "import com.x.Abs;"


def test_returns_empty_when_no_src_main_java(tmp_path):
    m = build_project_imports(str(tmp_path))
    assert m == {}


def test_s1_injects_from_project_map(tmp_path):
    """End-to-end: a test references TransactionStatusCode but no prod_import has it.
    _auto_inject_missing_imports must consult the project map and inject."""
    _make_project(str(tmp_path), {
        "com/caju/enums/TransactionStatusCode.java": (
            "package com.caju.enums;\npublic enum TransactionStatusCode { APPROVED }"
        ),
    })
    proj_map = build_project_imports(str(tmp_path))
    test_code = '''package com.caju.test;
import org.junit.jupiter.api.Test;

class Foo {
    @Test
    void t() {
        var x = TransactionStatusCode.APPROVED;
    }
}'''
    out = _auto_inject_missing_imports(
        test_code,
        prod_imports=[],         # production class doesn't import it
        project_imports=proj_map,
    )
    assert "import com.caju.enums.TransactionStatusCode;" in out


def test_s1_prod_imports_take_precedence_over_project_map(tmp_path):
    """If a class is in prod_imports, use that — don't override with project map."""
    _make_project(str(tmp_path), {
        "com/wrong/Foo.java": "package com.wrong;\npublic class Foo {}",
    })
    proj_map = build_project_imports(str(tmp_path))
    test_code = '''class T { void t() { new Foo(); } }'''
    out = _auto_inject_missing_imports(
        test_code,
        prod_imports=["import com.right.Foo;"],
        project_imports=proj_map,
    )
    # prod import wins
    assert "import com.right.Foo;" in out
    assert "import com.wrong.Foo;" not in out


def test_s1_works_without_project_map():
    """Backwards compat: callers that don't pass project_imports still work."""
    test_code = '''class T { void t() { var bd = new BigDecimal("1"); } }'''
    out = _auto_inject_missing_imports(test_code, prod_imports=[])
    # BigDecimal is in _JDK_IMPORT_MAP
    assert "import java.math.BigDecimal;" in out
