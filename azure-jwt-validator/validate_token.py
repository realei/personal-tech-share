"""Azure AD JWT token validation debug script.

Structure intentionally mirrors ``lia_api/core/auth.py`` so that findings
(the audience / issuer combination that actually works) can be copy-pasted
back into the production validator without translating syntax.

Differences vs. auth.py:
- Sync (no asyncio) — single-shot debug script.
- ``validate_all`` tries every (audience, issuer) combination and returns
  every attempt, instead of breaking on the first success.
- No database / revocation checks — verification only.

Usage:
    python validate_token.py --config config.json
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# JWKS cache TTL in seconds (24 hours) — matches auth.py:_JWKS_CACHE_TTL
_JWKS_CACHE_TTL = 24 * 60 * 60


# ─────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────


@dataclass
class Config:
    """Parsed config file contents."""

    tenant_id: str
    client_id: str
    token: str
    app_id_uri: str = ""
    audiences: list[str] = field(default_factory=list)  # extra audiences to try
    issuers: list[str] = field(default_factory=list)  # extra issuer templates to try
    verify_exp: bool = True


def load_config(path: str) -> Config:
    """Load and validate a JSON config file."""
    with open(path) as f:
        raw = json.load(f)

    required = ["tenant_id", "client_id", "token"]
    missing = [k for k in required if not raw.get(k)]
    if missing:
        raise ValueError(f"Missing required config fields: {', '.join(missing)}")

    return Config(
        tenant_id=raw["tenant_id"],
        client_id=raw["client_id"],
        token=raw["token"],
        app_id_uri=raw.get("app_id_uri", ""),
        audiences=raw.get("audiences", []),
        issuers=raw.get("issuers", []),
        verify_exp=raw.get("verify_exp", True),
    )


# ─────────────────────────────────────────────────────────
# Audience / issuer expansion
# ─────────────────────────────────────────────────────────


def build_audiences(config: Config) -> list[str]:
    """Default audiences (mirrors auth.py:75-77) + user-provided, deduped."""
    defaults = [config.client_id, f"api://{config.client_id}"]
    if config.app_id_uri:
        defaults.append(config.app_id_uri)

    seen: set[str] = set()
    result: list[str] = []
    for aud in defaults + list(config.audiences):
        if aud and aud not in seen:
            seen.add(aud)
            result.append(aud)
    return result


def expand_issuers(config: Config) -> list[str]:
    """Substitute ``{tenant_id}`` in issuer templates; fall back to the v2 default."""
    # Default issuer — mirrors auth.py:49-50
    default_issuer = f"https://login.microsoftonline.com/{config.tenant_id}/v2.0"

    if not config.issuers:
        return [default_issuer]

    return [iss.replace("{tenant_id}", config.tenant_id) for iss in config.issuers]


# ─────────────────────────────────────────────────────────
# Validation — mirrors auth.py TokenValidator
# ─────────────────────────────────────────────────────────


@dataclass
class Attempt:
    """Result of a single (audience, issuer) verification attempt."""

    audience: str
    issuer: str
    success: bool
    error: str | None
    payload: dict[str, Any] | None


class TokenValidator:
    """Debug variant of auth.py TokenValidator.

    Tries every ``(audience, issuer)`` combination and records every result.
    """

    def __init__(self, tenant_id: str, client_id: str, app_id_uri: str = ""):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.app_id_uri = app_id_uri
        self._jwks: dict | None = None
        self._jwks_fetched_at: float = 0

    @property
    def jwks_uri(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"

    def get_jwks(self) -> dict:
        """Fetch JSON Web Key Set from Azure AD with TTL-based caching.

        Sync variant of auth.py:56 (original is async).
        """
        now = time.time()
        if self._jwks is None or (now - self._jwks_fetched_at) > _JWKS_CACHE_TTL:
            with httpx.Client() as client:
                response = client.get(self.jwks_uri)
                response.raise_for_status()
                self._jwks = response.json()
                self._jwks_fetched_at = now
        assert self._jwks is not None
        return self._jwks

    def validate_all(
        self,
        token: str,
        audiences: list[str],
        issuers: list[str],
        verify_exp: bool = True,
    ) -> list[Attempt]:
        """Try every (audience x issuer) combination; return all attempts.

        Mirrors the inner try/except loop of auth.py:80-92, but collects
        every result instead of breaking on first success.
        """
        jwks = self.get_jwks()
        attempts: list[Attempt] = []

        for iss in issuers:
            for aud in audiences:
                try:
                    payload = jwt.decode(
                        token,
                        jwks,
                        algorithms=["RS256"],
                        audience=aud,
                        issuer=iss,
                        options={"verify_exp": verify_exp},
                    )
                    attempts.append(Attempt(aud, iss, True, None, payload))
                except JWTError as e:
                    attempts.append(Attempt(aud, iss, False, str(e), None))

        return attempts


# ─────────────────────────────────────────────────────────
# Unverified decode — for showing what's actually in the token
# ─────────────────────────────────────────────────────────


def decode_unverified(token: str) -> dict[str, Any]:
    """Decode the token without verifying signature / audience / issuer / exp."""
    return jwt.get_unverified_claims(token)


# ─────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────


def _humanize_delta(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d"


def _format_timestamp(ts: Any) -> str:
    if not isinstance(ts, (int, float)):
        return str(ts)
    t = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))
    delta = ts - time.time()
    if delta < 0:
        return f"{t}  (expired {_humanize_delta(-delta)} ago)"
    return f"{t}  (valid for {_humanize_delta(delta)})"


# Claims shown in the unverified-decode section, in display order.
_DISPLAY_CLAIMS = (
    "aud",
    "iss",
    "exp",
    "iat",
    "nbf",
    "tid",
    "oid",
    "sub",
    "preferred_username",
    "email",
    "name",
    "roles",
    "scp",
    "appid",
)


def format_report(unverified: dict[str, Any], attempts: list[Attempt]) -> str:
    """Build the human-readable report string."""
    lines: list[str] = []
    bar = "=" * 72

    lines.append(bar)
    lines.append("Token claims (decoded WITHOUT signature verification)")
    lines.append(bar)
    for key in _DISPLAY_CLAIMS:
        if key in unverified:
            val = unverified[key]
            if key in ("exp", "iat", "nbf"):
                val = _format_timestamp(val)
            lines.append(f"  {key:<22}: {val}")
    lines.append("")

    n_aud = len({a.audience for a in attempts})
    n_iss = len({a.issuer for a in attempts})
    lines.append(bar)
    lines.append(
        f"Validation attempts ({n_aud} audiences x {n_iss} issuers = {len(attempts)})"
    )
    lines.append(bar)

    aud_w = max((len(a.audience) for a in attempts), default=0)
    iss_w = max((len(a.issuer) for a in attempts), default=0)

    for a in attempts:
        mark = "PASS" if a.success else "FAIL"
        line = f"  [{mark}]  aud={a.audience:<{aud_w}}  iss={a.issuer:<{iss_w}}"
        if not a.success and a.error:
            line += f"  -> {a.error}"
        lines.append(line)
    lines.append("")

    lines.append(bar)
    passing = [a for a in attempts if a.success]
    if passing:
        lines.append("Result: VALID combination(s) found:")
        for a in passing:
            lines.append(f"  - aud={a.audience}")
            lines.append(f"    iss={a.issuer}")
    else:
        lines.append("Result: NO valid (audience, issuer) combination.")
        lines.append(
            "Compare the unverified 'aud' / 'iss' above with the attempted values."
        )
    lines.append(bar)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# CLI entry
# ─────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an Azure AD JWT against multiple audience/issuer combinations."
    )
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        config = load_config(args.config)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        logger.error("Failed to load config: %s", e)
        return 2

    audiences = build_audiences(config)
    issuers = expand_issuers(config)

    validator = TokenValidator(
        tenant_id=config.tenant_id,
        client_id=config.client_id,
        app_id_uri=config.app_id_uri,
    )

    try:
        unverified = decode_unverified(config.token)
    except JWTError as e:
        logger.error("Token is not a decodable JWT: %s", e)
        return 2

    try:
        attempts = validator.validate_all(
            config.token, audiences, issuers, config.verify_exp
        )
    except Exception as e:
        logger.error("Failed to fetch JWKS or run validation: %s", e)
        return 2

    print(format_report(unverified, attempts))

    return 0 if any(a.success for a in attempts) else 1


if __name__ == "__main__":
    sys.exit(main())
