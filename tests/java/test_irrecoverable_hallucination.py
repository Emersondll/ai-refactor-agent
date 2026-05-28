import pytest
from java.refactor import _is_irrecoverable_hallucination, _JDK_IMPORT_MAP


def test_method_does_not_exist_with_no_prod_match_is_irrecoverable():
    # _categorize_build_error returned this prefix for getCode() on TransactionCodeModel
    repair_hint = (
        "METHOD ERROR: You called 'method getCode()' which DOES NOT EXIST in the class.\n"
        "Check the exact signatures of the source class and use only real methods."
    )
    # Production class doesn't have getCode in any imported symbol
    prod_imports = [
        "import org.springframework.web.bind.annotation.PostMapping;",
        "import com.caju.transactionauthorizer.model.TransactionCodeModel;",
    ]
    assert _is_irrecoverable_hallucination(repair_hint, prod_imports) is True


def test_import_error_for_hallucinated_class_is_irrecoverable():
    repair_hint = (
        "IMPORT ERROR: Class 'MerchantCodesServiceImpl' not found.\n"
        "Add the correct import. Use only classes that exist in the project."
    )
    prod_imports = [
        "import com.caju.transactionauthorizer.service.MerchantCategoryCodesService;",
    ]
    assert _is_irrecoverable_hallucination(repair_hint, prod_imports) is True


def test_import_error_for_real_jdk_class_is_recoverable():
    """If the missing class is a known JDK type, S2 can inject the import — recoverable."""
    repair_hint = "IMPORT ERROR: Class `BigDecimal` is missing its import.\nADD THIS EXACT LINE..."
    prod_imports = []
    # BigDecimal IS in _JDK_IMPORT_MAP — repair_hint already names the fix → recoverable
    assert _is_irrecoverable_hallucination(repair_hint, prod_imports) is False


def test_import_error_for_known_prod_class_is_recoverable():
    """If the missing class IS in prod_imports, S1 can inject — recoverable."""
    repair_hint = (
        "IMPORT ERROR: Class `MerchantDocument` is missing its import.\nADD THIS EXACT LINE..."
    )
    prod_imports = ["import com.caju.transactionauthorizer.document.MerchantDocument;"]
    assert _is_irrecoverable_hallucination(repair_hint, prod_imports) is False


def test_assertion_error_is_not_irrecoverable():
    """Assertion mismatches are fixable by the LLM (or by P4 surgical patch)."""
    repair_hint = (
        "ASSERTION WRONG EXPECTED VALUE:\n"
        "  Your test expects: <5.00>\n  Actual return value: <50.00>"
    )
    assert _is_irrecoverable_hallucination(repair_hint, []) is False


def test_static_import_error_is_recoverable():
    """JUnit assertion methods missing the static import — P2 injects it."""
    repair_hint = (
        "STATIC IMPORT ERROR: JUnit 5 assertion method not found in scope.\n"
        "ADD THIS LINE to your import block (copy verbatim):\n"
        "  import static org.junit.jupiter.api.Assertions.*;"
    )
    assert _is_irrecoverable_hallucination(repair_hint, []) is False


def test_constructor_error_is_not_irrecoverable():
    """Constructor count mismatch is now caught by _fix_constructor_calls pre-Maven —
    and even if reached, the dep_context hint guides repair. Recoverable."""
    repair_hint = (
        "CONSTRUCTOR ERROR: You called the constructor with wrong arguments.\n"
        "  Required: String, BigDecimal\n  Found: String"
    )
    assert _is_irrecoverable_hallucination(repair_hint, []) is False


def test_method_error_with_real_prod_class_match_is_recoverable():
    """If the 'missing method' name matches a known method in prod_imports
    (the symbol IS findable), it's a typo — repairable. Conservative: we
    only flag irrecoverable when the symbol is NOT findable anywhere."""
    repair_hint = (
        "METHOD ERROR: You called 'method getName()' which DOES NOT EXIST in the class.\n"
    )
    # We don't have access to the method bodies; we only know prod_imports.
    # Heuristic: if the method name is generic enough (≤3 chars or common bean getter),
    # treat as recoverable — could be a typo. For getCode/getName specifically,
    # we cannot tell from prod_imports alone. The conservative call: irrecoverable
    # only when we have a strong signal (long unique class/method names).
    # For this test, getName is a very common name → treat as RECOVERABLE.
    assert _is_irrecoverable_hallucination(repair_hint, []) is False


def test_extracts_class_name_correctly():
    repair_hint = "IMPORT ERROR: Class 'FooBarBaz' not found."
    # FooBarBaz not in prod_imports → irrecoverable
    assert _is_irrecoverable_hallucination(repair_hint, []) is True
    # FooBarBaz IS in prod_imports → recoverable
    assert _is_irrecoverable_hallucination(
        repair_hint, ["import com.example.FooBarBaz;"]
    ) is False


# ---------------------------------------------------------------------------
# Option 9: hallucination detection via test_code scan
# ---------------------------------------------------------------------------


def test_package_error_with_unknown_class_in_test_code_is_irrecoverable():
    """LLM wrote `TotallyMadeUp.X` somewhere in test_code → PACKAGE ERROR.
    The class is in no known map → irrecoverable."""
    repair_hint = (
        "PACKAGE ERROR: An import points to a package that does not exist.\n"
        "Use only classes from the project — check the DEPENDENCY CONTEXT."
    )
    test_code = '''package x;
import org.junit.jupiter.api.Test;
class FooTest {
    @Test
    void t() {
        var z = TotallyMadeUp.SOME_CONSTANT;
    }
}'''
    assert _is_irrecoverable_hallucination(
        repair_hint, prod_imports=[],
        test_code=test_code, project_imports={},
    ) is True


def test_package_error_with_class_in_project_map_is_recoverable():
    """LLM wrote TransactionStatusCode.X but it IS in project_imports.
    S1 should have injected it next round → not irrecoverable."""
    repair_hint = "PACKAGE ERROR: An import points to a package that does not exist."
    test_code = "class T { void t() { var z = TransactionStatusCode.APPROVED; } }"
    project_imports = {
        "TransactionStatusCode": "import com.caju.enums.TransactionStatusCode;",
    }
    assert _is_irrecoverable_hallucination(
        repair_hint, prod_imports=[],
        test_code=test_code, project_imports=project_imports,
    ) is False


def test_package_error_with_known_jdk_class_is_recoverable():
    """LLM wrote BigDecimal.ZERO — JDK map has BigDecimal → S1 injects → recoverable."""
    repair_hint = "PACKAGE ERROR: An import points to a package that does not exist."
    test_code = "class T { void t() { var z = BigDecimal.ZERO; } }"
    assert _is_irrecoverable_hallucination(
        repair_hint, prod_imports=[],
        test_code=test_code, project_imports={},
    ) is False


def test_package_error_without_test_code_falls_through():
    """If test_code is not passed, function uses old logic (no scan) — defensive default."""
    repair_hint = "PACKAGE ERROR: An import points to a package that does not exist."
    # Without test_code, can't scan — return False (don't fail-fast on uncertainty)
    result = _is_irrecoverable_hallucination(repair_hint, prod_imports=[])
    # Conservative: with no test_code, we cannot detect hallucination → False (recoverable)
    assert result is False


def test_known_spring_class_in_test_code_is_recoverable():
    """Spring framework classes like HttpStatus, ResponseEntity, MediaType
    are common and should NOT be flagged as hallucinations."""
    repair_hint = "PACKAGE ERROR: An import points to a package that does not exist."
    test_code = '''class T {
        void t() {
            assertEquals(HttpStatus.OK, ResponseEntity.ok().getStatusCode());
        }
    }'''
    assert _is_irrecoverable_hallucination(
        repair_hint, prod_imports=[],
        test_code=test_code, project_imports={},
    ) is False


def test_constants_lowercase_after_class_dot_not_flagged():
    """Field access like `x.field` (lowercase after dot) is NOT a class.MEMBER pattern."""
    repair_hint = "PACKAGE ERROR: An import points to a package that does not exist."
    test_code = "class T { void t() { var z = someVar.method(); } }"
    # someVar is lowercase — not a class reference — and even if scanned, no unknown class
    assert _is_irrecoverable_hallucination(
        repair_hint, prod_imports=[],
        test_code=test_code, project_imports={},
    ) is False


def test_multiple_classes_one_unknown_is_irrecoverable():
    """Only one unknown class is enough to flag as irrecoverable."""
    repair_hint = "PACKAGE ERROR: An import points to a package that does not exist."
    test_code = '''class T {
        void t() {
            var ok1 = HttpStatus.OK;
            var ok2 = BigDecimal.ZERO;
            var bad = SomeRandomHallucination.NOPE;
        }
    }'''
    assert _is_irrecoverable_hallucination(
        repair_hint, prod_imports=[],
        test_code=test_code, project_imports={},
    ) is True


def test_existing_method_error_still_irrecoverable():
    """Pre-existing METHOD ERROR detection still works (regression check)."""
    repair_hint = (
        "METHOD ERROR: You called 'method getMadeUpThing()' which DOES NOT EXIST"
    )
    # Without test_code, falls back to old logic
    assert _is_irrecoverable_hallucination(repair_hint, prod_imports=[]) is True


def test_assertion_error_is_recoverable_regardless():
    """ASSERTION errors are never irrecoverable — even with hallucinated class names."""
    repair_hint = "ASSERTION WRONG EXPECTED VALUE: expected: <5> but was: <50>"
    test_code = "class T { void t() { TotallyMadeUp.X = 1; } }"
    assert _is_irrecoverable_hallucination(
        repair_hint, prod_imports=[],
        test_code=test_code, project_imports={},
    ) is False
