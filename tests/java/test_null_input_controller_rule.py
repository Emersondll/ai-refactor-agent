import pytest
from java.refactor import _build_active_rules


def _build(code):
    return _build_active_rules(
        original=code, _prod_imports=[],
        _self_import="import com.example.Ctrl;",
        _test_cls_name="CtrlTest",
        _test_pkg="com.example",
        complement_mode=False,
        rules="STUB",
    )


def test_rule_present_when_restcontroller_returns_responseentity():
    code = '''package com.example;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.PostMapping;

@RestController
public class Ctrl {
    @PostMapping
    public ResponseEntity<String> doIt(String input) {
        return ResponseEntity.ok().body(svc.handle(input));
    }
}'''
    out = _build(code)
    assert "CONTROLLER NULL-INPUT" in out.upper() or "NULL INPUT" in out.upper()


def test_rule_mentions_mock_must_be_set_to_return_null():
    code = '''package com.example;
import org.springframework.http.ResponseEntity;
@RestController
public class Ctrl {
    @PostMapping
    public ResponseEntity<X> doIt(Y in) { return ResponseEntity.ok().body(svc.call(in)); }
}'''
    out = _build(code)
    # Regra precisa avisar sobre mocks
    upper = out.upper()
    assert "MOCK" in upper or "thenReturn" in out


def test_rule_warns_against_blind_assertnull_on_body():
    code = '''package com.example;
import org.springframework.http.ResponseEntity;
@RestController
public class Ctrl {
    @PostMapping
    public ResponseEntity<X> doIt(Y in) { return ResponseEntity.ok().body(svc.call(in)); }
}'''
    out = _build(code)
    # A regra deve mencionar assertNull no contexto desse padrão
    assert "assertNull" in out


def test_no_rule_when_not_restcontroller():
    code = '''package com.example;
import org.springframework.http.ResponseEntity;
public class NotController {
    public ResponseEntity<X> doIt() { return ResponseEntity.ok().build(); }
}'''
    out = _build(code)
    assert "CONTROLLER NULL-INPUT" not in out.upper()


def test_no_rule_when_no_responseentity():
    code = '''package com.example;
import org.springframework.web.bind.annotation.RestController;
@RestController
public class Ctrl {
    @PostMapping
    public String doIt() { return "hi"; }
}'''
    out = _build(code)
    assert "CONTROLLER NULL-INPUT" not in out.upper()


def test_existing_responseentity_responsestatus_rule_still_works():
    """Regression: N4 rule (ResponseEntity + @ResponseStatus) coexists."""
    code = '''package com.example;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
@RestController
public class Ctrl {
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ResponseEntity<X> doIt() { return ResponseEntity.ok().build(); }
}'''
    out = _build(code)
    # Both rules present
    assert "RESPONSEENTITY" in out.upper()  # N4
    assert "CONTROLLER NULL-INPUT" in out.upper() or "NULL INPUT" in out.upper()  # N10
