"""Unit tests for validate_token.py.

Tests run fully offline:
- RSA keypair generated in-memory via conftest fixtures.
- Tokens signed locally.
- TokenValidator.get_jwks is monkeypatched to return the fixture JWKS.
"""

import json
import time

import pytest

import validate_token as vt


# ─────────────────────────────────────────────────────────
# build_audiences
# ─────────────────────────────────────────────────────────


def test_build_audiences_includes_defaults():
    cfg = vt.Config(
        tenant_id="t",
        client_id="client-id",
        token="x",
        app_id_uri="api://app-uri",
    )
    result = vt.build_audiences(cfg)
    assert "client-id" in result
    assert "api://client-id" in result
    assert "api://app-uri" in result


def test_build_audiences_dedups_against_defaults():
    cfg = vt.Config(
        tenant_id="t",
        client_id="client-id",
        token="x",
        audiences=["client-id", "extra"],
    )
    result = vt.build_audiences(cfg)
    assert result.count("client-id") == 1
    assert "extra" in result


def test_build_audiences_skips_empty_app_id_uri():
    cfg = vt.Config(tenant_id="t", client_id="c", token="x", app_id_uri="")
    result = vt.build_audiences(cfg)
    assert "" not in result


def test_build_audiences_preserves_order():
    cfg = vt.Config(
        tenant_id="t",
        client_id="client-id",
        token="x",
        app_id_uri="api://app-uri",
        audiences=["extra-1", "extra-2"],
    )
    result = vt.build_audiences(cfg)
    # Defaults come first, then user-provided.
    assert result == [
        "client-id",
        "api://client-id",
        "api://app-uri",
        "extra-1",
        "extra-2",
    ]


# ─────────────────────────────────────────────────────────
# expand_issuers
# ─────────────────────────────────────────────────────────


def test_expand_issuers_default_when_empty():
    cfg = vt.Config(tenant_id="test-tenant", client_id="c", token="x")
    result = vt.expand_issuers(cfg)
    assert result == ["https://login.microsoftonline.com/test-tenant/v2.0"]


def test_expand_issuers_substitutes_template():
    cfg = vt.Config(
        tenant_id="my-tenant",
        client_id="c",
        token="x",
        issuers=[
            "https://login.microsoftonline.com/{tenant_id}/v2.0",
            "https://sts.windows.net/{tenant_id}/",
        ],
    )
    result = vt.expand_issuers(cfg)
    assert result == [
        "https://login.microsoftonline.com/my-tenant/v2.0",
        "https://sts.windows.net/my-tenant/",
    ]


# ─────────────────────────────────────────────────────────
# load_config
# ─────────────────────────────────────────────────────────


def test_load_config_missing_required_raises(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"client_id": "c"}))
    with pytest.raises(ValueError, match="Missing required"):
        vt.load_config(str(path))


def test_load_config_invalid_json_raises(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("not json")
    with pytest.raises(json.JSONDecodeError):
        vt.load_config(str(path))


def test_load_config_full(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(
        json.dumps(
            {
                "tenant_id": "t",
                "client_id": "c",
                "token": "xyz",
                "app_id_uri": "api://u",
                "audiences": ["a1"],
                "issuers": ["i1"],
                "verify_exp": False,
            }
        )
    )
    cfg = vt.load_config(str(path))
    assert cfg.tenant_id == "t"
    assert cfg.audiences == ["a1"]
    assert cfg.issuers == ["i1"]
    assert cfg.verify_exp is False


def test_load_config_minimal(tmp_path):
    """Only required fields provided — defaults should apply."""
    path = tmp_path / "c.json"
    path.write_text(
        json.dumps({"tenant_id": "t", "client_id": "c", "token": "xyz"})
    )
    cfg = vt.load_config(str(path))
    assert cfg.audiences == []
    assert cfg.issuers == []
    assert cfg.verify_exp is True


# ─────────────────────────────────────────────────────────
# decode_unverified
# ─────────────────────────────────────────────────────────


def test_decode_unverified_returns_actual_claims(make_token):
    token = make_token(aud="api://real", iss="https://real-issuer/")
    claims = vt.decode_unverified(token)
    assert claims["aud"] == "api://real"
    assert claims["iss"] == "https://real-issuer/"


# ─────────────────────────────────────────────────────────
# TokenValidator.validate_all
# ─────────────────────────────────────────────────────────


@pytest.fixture
def validator(monkeypatch, fake_jwks):
    """TokenValidator with get_jwks patched to return the fixture JWKS."""
    v = vt.TokenValidator(tenant_id="test-tenant", client_id="test-client")
    monkeypatch.setattr(v, "get_jwks", lambda: fake_jwks)
    return v


def test_valid_combination_passes(validator, make_token):
    token = make_token(
        aud="api://test-client",
        iss="https://login.microsoftonline.com/test-tenant/v2.0",
    )
    attempts = validator.validate_all(
        token,
        audiences=["api://test-client", "other-aud"],
        issuers=[
            "https://login.microsoftonline.com/test-tenant/v2.0",
            "https://sts.windows.net/test-tenant/",
        ],
    )
    passing = [a for a in attempts if a.success]
    assert len(passing) == 1
    assert passing[0].audience == "api://test-client"
    assert passing[0].issuer == "https://login.microsoftonline.com/test-tenant/v2.0"
    assert passing[0].payload is not None
    assert passing[0].payload["tid"] == "test-tenant"


def test_no_matching_combination_fails(validator, make_token):
    token = make_token(aud="api://actual", iss="https://actual-issuer/")
    attempts = validator.validate_all(
        token,
        audiences=["other1", "other2"],
        issuers=["https://wrong/"],
    )
    assert len(attempts) == 2
    assert all(not a.success for a in attempts)
    assert all(a.error for a in attempts)


def test_v1_vs_v2_issuer_format(validator, make_token):
    """Token issued with v1 issuer only validates against v1 issuer entry."""
    token = make_token(
        aud="api://test",
        iss="https://sts.windows.net/test-tenant/",
    )
    attempts = validator.validate_all(
        token,
        audiences=["api://test"],
        issuers=[
            "https://login.microsoftonline.com/test-tenant/v2.0",
            "https://sts.windows.net/test-tenant/",
        ],
    )
    passing = [a for a in attempts if a.success]
    assert len(passing) == 1
    assert passing[0].issuer == "https://sts.windows.net/test-tenant/"


def test_expired_token_fails_when_verify_exp_true(validator, make_token):
    token = make_token(
        aud="api://test",
        iss="https://login.microsoftonline.com/test-tenant/v2.0",
        exp=int(time.time()) - 60,
    )
    attempts = validator.validate_all(
        token,
        audiences=["api://test"],
        issuers=["https://login.microsoftonline.com/test-tenant/v2.0"],
        verify_exp=True,
    )
    assert not attempts[0].success


def test_expired_token_passes_when_verify_exp_false(validator, make_token):
    token = make_token(
        aud="api://test",
        iss="https://login.microsoftonline.com/test-tenant/v2.0",
        exp=int(time.time()) - 60,
    )
    attempts = validator.validate_all(
        token,
        audiences=["api://test"],
        issuers=["https://login.microsoftonline.com/test-tenant/v2.0"],
        verify_exp=False,
    )
    assert attempts[0].success


def test_bad_signature_fails_all(
    validator, make_token_with_key, other_rsa_keypair
):
    """Token signed with a different key must fail every combination."""
    token = make_token_with_key(
        other_rsa_keypair,
        aud="api://test",
        iss="https://login.microsoftonline.com/test-tenant/v2.0",
    )
    attempts = validator.validate_all(
        token,
        audiences=["api://test"],
        issuers=["https://login.microsoftonline.com/test-tenant/v2.0"],
    )
    assert all(not a.success for a in attempts)


def test_attempt_count_equals_product(validator, make_token):
    token = make_token()
    attempts = validator.validate_all(
        token,
        audiences=["a1", "a2", "a3"],
        issuers=["i1", "i2"],
    )
    assert len(attempts) == 6


# ─────────────────────────────────────────────────────────
# format_report
# ─────────────────────────────────────────────────────────


def test_format_report_contains_pass_and_fail_markers():
    unverified = {"aud": "x", "iss": "y", "exp": 0}
    attempts = [
        vt.Attempt("aud1", "iss1", True, None, {"ok": True}),
        vt.Attempt("aud2", "iss1", False, "Invalid audience", None),
    ]
    report = vt.format_report(unverified, attempts)
    assert "[PASS]" in report
    assert "[FAIL]" in report
    assert "Invalid audience" in report
    assert "Result: VALID" in report


def test_format_report_no_valid_combo():
    unverified = {"aud": "x", "iss": "y"}
    attempts = [vt.Attempt("a", "i", False, "err", None)]
    report = vt.format_report(unverified, attempts)
    assert "NO valid" in report


def test_format_report_shows_expiry_humanized():
    unverified = {"aud": "x", "iss": "y", "exp": int(time.time()) - 120}
    attempts = [vt.Attempt("a", "i", False, "err", None)]
    report = vt.format_report(unverified, attempts)
    assert "expired" in report
