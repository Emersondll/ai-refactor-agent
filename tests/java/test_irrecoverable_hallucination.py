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
