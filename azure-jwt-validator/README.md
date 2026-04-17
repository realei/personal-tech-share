# azure-jwt-validator

A tiny debug script that validates an Azure AD JWT against a matrix of
candidate **audiences** and **issuers**, and tells you which combination
(if any) passes.

Use it when you're not sure what `aud` or `iss` a token actually has, or
what the API should accept. The code structure is kept close to a
production `TokenValidator` so the working combination can be copy-pasted
back into your auth layer.

## What it does

For the given token, the script:

1. **Decodes without verification** and prints the actual `aud`, `iss`,
   `exp`, `tid`, `oid`, and other claims — so you can see what the token
   really looks like.
2. **Iterates** over every `(audience × issuer)` combination, calling
   `jose.jwt.decode` with full signature / audience / issuer / expiry
   checks.
3. **Prints a report** marking each attempt `PASS` or `FAIL` with the
   reason, and summarizes which combination(s) worked.

## Setup

```bash
cd azure-jwt-validator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

1. Copy the example config:

   ```bash
   cp config.example.json config.json
   ```

2. Fill in `tenant_id`, `client_id`, and paste the `token`. Add any
   extra `audiences` / `issuers` you want to try.

3. Run:

   ```bash
   python validate_token.py --config config.json
   ```

Exit codes: `0` if at least one combination passes, `1` if none pass,
`2` on config / token parsing errors.

`config.json` is gitignored — it may hold real tokens, do not commit it.

## Config fields

| Field         | Required | Notes                                                                                                 |
|---------------|:--------:|-------------------------------------------------------------------------------------------------------|
| `tenant_id`   | yes      | Azure AD tenant GUID.                                                                                 |
| `client_id`   | yes      | App registration client ID.                                                                           |
| `token`       | yes      | The JWT string to validate.                                                                           |
| `app_id_uri`  | no       | Application ID URI (e.g. `api://...`). Added to the default audience list when present.               |
| `audiences`   | no       | Extra candidate audiences. Merged with `[client_id, api://client_id, app_id_uri]` and deduped.        |
| `issuers`     | no       | Candidate issuer URLs. `{tenant_id}` is substituted. Defaults to the v2.0 issuer when empty.          |
| `verify_exp`  | no       | Set to `false` to skip expiry checking (useful for inspecting expired tokens). Default `true`.        |

### Typical issuers to try

```json
"issuers": [
  "https://login.microsoftonline.com/{tenant_id}/v2.0",
  "https://sts.windows.net/{tenant_id}/"
]
```

The first is the Azure AD **v2.0** issuer; the second is the legacy
**v1.0** issuer. Tokens issued via different endpoints carry different
`iss` values, which is a very common source of validation failures.

## Example output

```
========================================================================
Token claims (decoded WITHOUT signature verification)
========================================================================
  aud                   : api://yyyyyyyy-yyyy-...
  iss                   : https://sts.windows.net/xxxxxxxx-.../
  exp                   : 2026-04-17 10:30:00 UTC  (expired 2h12m ago)
  tid                   : xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  oid                   : zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz

========================================================================
Validation attempts (3 audiences x 2 issuers = 6)
========================================================================
  [PASS]  aud=api://yyyy...   iss=https://sts.windows.net/xxxx/
  [FAIL]  aud=api://yyyy...   iss=https://login.microsoftonline.com/../v2.0  -> Invalid issuer
  [FAIL]  aud=yyyy-...        iss=https://sts.windows.net/xxxx/              -> Invalid audience
  ...
========================================================================
Result: VALID combination(s) found:
  - aud=api://yyyy...
    iss=https://sts.windows.net/xxxx/
========================================================================
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

All tests are fully offline. They generate an RSA keypair in memory,
sign tokens locally, and monkeypatch `TokenValidator.get_jwks`. No
network or real Azure AD access is needed to run them.

## Sharing with others (minimal file set)

Colleagues who just want to run the debug script only need:

```
validate_token.py
config.example.json
requirements.txt
README.md
```

They do **not** need the `tests/` directory or `requirements-dev.txt`.
