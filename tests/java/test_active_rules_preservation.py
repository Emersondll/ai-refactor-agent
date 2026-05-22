"""Regression tests for _build_active_rules() — P3 consolidation.

Verifies that all 18 key phrases from prior bug-fixes survive the prompt
consolidation done in P3 (merged IMPORTS blocks, compressed conditional
blocks, stated mandatory-ness once globally).

Run with:
    python -m pytest tests/java/test_active_rules_preservation.py -v
"""

import sys
import os

# Make sure the project root is on sys.path so we can import java.refactor
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from java.refactor import _build_active_rules  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A class that triggers EVERY conditional block:
#   - NOT a record (no record keyword)
#   - BigDecimal field
#   - java.sql.Timestamp + import
#   - @Document (MongoDB)
#   - @Autowired field injection
#   - Parameterized constructor (triggers setter/getter block)
CLASS_WITH_ALL_CONDITIONS = """\
package com.acme.service;

import java.math.BigDecimal;
import java.sql.Timestamp;
import com.acme.repository.OrderRepository;
import org.springframework.data.mongodb.core.mapping.Document;
import org.springframework.beans.factory.annotation.Autowired;

@Document
public class OrderService {

    @Autowired
    private OrderRepository orderRepository;

    private BigDecimal amount;
    private Timestamp createdAt;

    public OrderService(BigDecimal amount, Timestamp createdAt) {
        this.amount = amount;
        this.createdAt = createdAt;
    }

    public BigDecimal getAmount() { return amount; }
    public void setAmount(BigDecimal amount) { this.amount = amount; }

    public Timestamp getCreatedAt() { return createdAt; }
    public void setCreatedAt(Timestamp createdAt) { this.createdAt = createdAt; }
}
"""

_ALL_PROD_IMPORTS = [
    "import java.math.BigDecimal;",
    "import java.sql.Timestamp;",
    "import com.acme.repository.OrderRepository;",
    "import org.springframework.data.mongodb.core.mapping.Document;",
    "import org.springframework.beans.factory.annotation.Autowired;",
]
_SELF_IMPORT = "import com.acme.service.OrderService;"

RECORD_CLASS = """\
package com.acme.dto;

public record MoneyRecord(String currency, java.math.BigDecimal amount) {}
"""

_RECORD_PROD_IMPORTS = ["import java.math.BigDecimal;"]
_RECORD_SELF_IMPORT = "import com.acme.dto.MoneyRecord;"

_STUB_RULES = "# stub skill rules\n"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build(original, prod_imports, self_import, cls_name="OrderServiceTest",
           pkg="com.acme.service", rules=_STUB_RULES):
    return _build_active_rules(
        original=original,
        _prod_imports=prod_imports,
        _self_import=self_import,
        _test_cls_name=cls_name,
        _test_pkg=pkg,
        complement_mode=False,
        rules=rules,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_all_18_key_phrases_present():
    """Every key phrase from prior fixes must survive the P3 consolidation."""
    result = _build(
        CLASS_WITH_ALL_CONDITIONS,
        _ALL_PROD_IMPORTS,
        _SELF_IMPORT,
    )

    key_phrases = [
        # 1 — _mandatory_prefix
        ("MUST be EXACTLY", "phrase 1: MUST be EXACTLY"),
        # 2 — _mandatory_prefix
        ("NEVER use com.example.*", "phrase 2: NEVER use com.example.*"),
        # 3 — new IMPORTS block
        ("Use ONLY these import paths", "phrase 3: Use ONLY these import paths"),
        # 4 — SELF-IMPORT in new IMPORTS block
        ("SELF-IMPORT", "phrase 4: SELF-IMPORT"),
        # 5 — IMPORTS prohibition
        ("derive paths ONLY", "phrase 5: derive paths ONLY"),
        # 6 — BIGDECIMAL correct example
        ('new BigDecimal("100.00")', 'phrase 6: new BigDecimal("100.00")'),
        # 7 — BIGDECIMAL wrong example (String literal)
        ('"100.00"', 'phrase 7: "100.00" string literal'),
        # 8 — SETTER/GETTER wrong example
        ("assertNull(object.getX()) before calling setX()",
         "phrase 8: assertNull(object.getX()) before calling setX()"),
        # 9 — SETTER/GETTER correct example
        ("assertEquals(newValue, object.getX())",
         "phrase 9: assertEquals(newValue, object.getX())"),
        # 10 — TIMESTAMP correct format
        ('Timestamp.valueOf("2023-01-15 10:00:00")',
         'phrase 10: Timestamp.valueOf("2023-01-15 10:00:00")'),
        # 11 — TIMESTAMP wrong format (ISO T)
        ("T10:00:00", "phrase 11: T10:00:00 (ISO wrong format)"),
        # 12 — FIELD INJECTION ExtendWith
        ("@ExtendWith(MockitoExtension.class)",
         "phrase 12: @ExtendWith(MockitoExtension.class)"),
        # 13 — FIELD INJECTION InjectMocks
        ("@InjectMocks", "phrase 13: @InjectMocks"),
        # 14 — MONGODB import
        ("import org.springframework.data.mongodb.core.mapping.Document;",
         "phrase 14: MongoDB Document import"),
        # 15 — NULL ASSERTIONS assertNull
        ("assertNull(result.getField())", "phrase 15: assertNull(result.getField())"),
        # 16 — NULL ASSERTIONS never assertEquals enum
        ("NEVER assertEquals(EnumValue, result.getField())",
         "phrase 16: NEVER assertEquals(EnumValue, result.getField())"),
    ]

    for phrase, label in key_phrases:
        assert phrase in result, f"missing: {label!r}\n\nFull active_rules:\n{result}"


def test_record_canonical_constructor_phrase():
    """When class is a Java record, 'canonical constructor' must appear."""
    result = _build(
        RECORD_CLASS,
        _RECORD_PROD_IMPORTS,
        _RECORD_SELF_IMPORT,
        cls_name="MoneyRecordTest",
        pkg="com.acme.dto",
    )
    assert "canonical constructor" in result, (
        "missing: phrase 17: canonical constructor\n\nFull active_rules:\n" + result
    )


def test_record_equals_hashcode_phrase():
    """When class is a Java record, 'equals/hashCode' must appear."""
    result = _build(
        RECORD_CLASS,
        _RECORD_PROD_IMPORTS,
        _RECORD_SELF_IMPORT,
        cls_name="MoneyRecordTest",
        pkg="com.acme.dto",
    )
    assert "equals/hashCode" in result, (
        "missing: phrase 18: equals/hashCode\n\nFull active_rules:\n" + result
    )


def test_record_phrases_absent_for_non_record():
    """'canonical constructor' should NOT appear for a plain class."""
    result = _build(
        CLASS_WITH_ALL_CONDITIONS,
        _ALL_PROD_IMPORTS,
        _SELF_IMPORT,
    )
    assert "canonical constructor" not in result, (
        "canonical constructor unexpectedly present for non-record class"
    )


def test_self_import_in_imports_block():
    """Self-import line must appear inside the consolidated ### IMPORTS block."""
    result = _build(
        CLASS_WITH_ALL_CONDITIONS,
        _ALL_PROD_IMPORTS,
        _SELF_IMPORT,
    )
    # The self-import value itself must be present
    assert _SELF_IMPORT in result, f"Self-import not found in result:\n{result}"


def test_no_prod_imports_skips_imports_block():
    """When _prod_imports is empty, the ### IMPORTS block is skipped entirely."""
    result = _build(
        "public class Minimal { }",
        [],          # no prod imports
        None,        # no self-import
        cls_name="MinimalTest",
        pkg="",
    )
    assert "Use ONLY these import paths" not in result


def test_mandatory_header_present_once():
    """The global mandatory header should appear exactly once."""
    result = _build(
        CLASS_WITH_ALL_CONDITIONS,
        _ALL_PROD_IMPORTS,
        _SELF_IMPORT,
    )
    count = result.count("ALL `###` BLOCKS BELOW ARE MANDATORY")
    assert count == 1, f"Expected 1 global mandatory header, got {count}"


def test_no_duplicate_mandatory_suffix_in_titles():
    """No individual block title should contain '(MANDATORY' after consolidation."""
    result = _build(
        CLASS_WITH_ALL_CONDITIONS,
        _ALL_PROD_IMPORTS,
        _SELF_IMPORT,
    )
    # Lines that are section titles (start with ###)
    title_lines = [ln for ln in result.splitlines() if ln.startswith("###")]
    violations = [ln for ln in title_lines if "(MANDATORY" in ln]
    assert not violations, (
        f"Found redundant (MANDATORY...) suffix in block title(s): {violations}"
    )
