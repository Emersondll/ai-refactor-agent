import pytest
from java.refactor import _build_active_rules


def _build(code):
    return _build_active_rules(
        original=code,
        _prod_imports=[],
        _self_import="import com.example.Foo;",
        _test_cls_name="FooTest",
        _test_pkg="com.example",
        complement_mode=False,
        rules="STUB",
    )


def test_rule_present_when_responseentity_and_responsestatus_coexist():
    code = '''package x;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.http.HttpStatus;

@RestController
public class Ctrl {
    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ResponseEntity<String> create() {
        return ResponseEntity.ok().body("ok");
    }
}'''
    out = _build(code)
    assert "RESPONSEENTITY" in out.upper() or "@ResponseStatus" in out
    assert "ignored" in out.lower() or "IGNORE" in out


def test_no_rule_when_no_responsestatus():
    code = '''package x;
import org.springframework.http.ResponseEntity;
@RestController
public class Ctrl {
    @PostMapping
    public ResponseEntity<String> create() { return ResponseEntity.ok().body("ok"); }
}'''
    out = _build(code)
    # No @ResponseStatus → no rule
    section = "RESPONSEENTITY"
    assert section not in out.upper() or "ignored" not in out.lower()


def test_no_rule_when_no_responseentity_return():
    """If method returns plain DTO (not ResponseEntity), @ResponseStatus WORKS — no warning needed."""
    code = '''package x;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.http.HttpStatus;

@RestController
public class Ctrl {
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public String create() { return "ok"; }
}'''
    out = _build(code)
    # @ResponseStatus is valid for non-ResponseEntity → no warning
    assert "RESPONSEENTITY" not in out.upper()


def test_rule_mentions_actual_status_comes_from_responseentity():
    code = '''package x;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ResponseStatus;
@RestController
public class Ctrl {
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ResponseEntity<String> hello() { return ResponseEntity.ok().build(); }
}'''
    out = _build(code)
    section_start = out.upper().find("RESPONSEENTITY")
    section = out[section_start:section_start + 600]
    assert "ResponseEntity" in section
    # The rule should tell to assert against the ResponseEntity status
    assert ".ok()" in section or "ok()" in section or "actual" in section.lower()
