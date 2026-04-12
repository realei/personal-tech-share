# DevSecOps Pipeline Overview

>  Dev VM → Git → CI/CD → Azure

---

## End-to-End Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  DEV VM (Ubuntu)                                                    │
│                                                                     │
│  Developer / Claude Code                                            │
│       │                                                             │
│       ├── git commit                                                │
│       │     ├─ pre-commit : gitleaks, format, no .env, large files  │
│       │     └─ commit-msg : conventional format + co-author         │
│       │                                                             │
│       └── git push                                                  │
│             └─ pre-push : pnpm lint + typecheck + ruff + mypy       │
└─────────────────────────┬───────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  GitHub (BeaconBay/Lia.Next)                                        │
│                                                                     │
│  feature/* ──► PR ──► main                                          │
│  fix/*     ──►                                                      │
│  chore/*   ──►                                                      │
└─────────────────────────┬───────────────────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
┌──────────────────────┐  ┌──────────────────────────────────────────┐
│  GitHub Actions (PR)  │  │  Azure DevOps (merge to main)            │
│                       │  │                                          │
│  ① lint-and-test      │  │  Build Stage                             │
│     pnpm lint         │  │    ├─ Generate .env.production            │
│     pnpm typecheck    │  │    ├─ Docker build (backend + frontend)   │
│     pnpm test         │  │    └─ Push images to ACR                  │
│                       │  │                                          │
│  ② backend-test       │  │  Deploy Stage                            │
│     ruff check        │  │    ├─ Configure App Service settings      │
│     mypy              │  │    ├─ Deploy backend container             │
│     pytest            │  │    ├─ Deploy frontend container            │
│                       │  │    └─ Health check                        │
│  ③ security-scan      │  │                                          │
│     Trivy (vuln)      │  └──────────────────────┬───────────────────┘
│     Gitleaks (secrets)│                          │
│                       │                          ▼
│  ④ sbom               │  ┌──────────────────────────────────────────┐
│     SPDX + CycloneDX  │  │  Azure Cloud (Dev Environment)           │
└──────────────────────┘  │                                          │
                          │  ┌─────────┐  ┌────────────────────────┐ │
  All 4 must pass         │  │ Entra ID│  │ Azure OpenAI / Foundry │ │
  before merge            │  └────┬────┘  └────────────┬───────────┘ │
                          │       │                     │             │
                          │       ▼                     ▼             │
                          │  ┌─────────┐  ┌──────────────────┐       │
                          │  │  APIM    │──│  App Service x2  │       │
                          │  │ (gateway)│  │  BE :8000  FE :80│       │
                          │  └─────────┘  └────────┬─────────┘       │
                          │                        │                  │
                          │          ┌─────────────┼──────────┐      │
                          │          ▼             ▼          ▼      │
                          │    ┌──────────┐ ┌──────────┐ ┌────────┐ │
                          │    │ Cosmos DB │ │   Blob   │ │Key Vault│ │
                          │    │ (11 cont)│ │ Storage  │ │(secrets)│ │
                          │    └──────────┘ └──────────┘ └────────┘ │
                          └──────────────────────────────────────────┘
```

---

## Security Checkpoints

```
Stage              Check                        Blocks?
─────────────────────────────────────────────────────────
Dev VM             Gitleaks (secret scan)        Yes — commit blocked
                   No .env files                 Yes — commit blocked
                   Private key detection         Yes — commit blocked
                   Lint + typecheck              Yes — push blocked
                                                 │
GitHub Actions     Trivy (CRITICAL/HIGH vuln)    Yes — PR blocked
                   Gitleaks (full history scan)  Yes — PR blocked
                   SBOM generation               No  — audit only
                                                 │
Azure DevOps       CodeQL (JS + Python)          No  — report only
                   Dependency scanning           No  — report only
                                                 │
Runtime            Entra ID (JWT auth)           Yes — 401 unauthorized
                   APIM (rate limit + secret)    Yes — 429 / 403
                   Key Vault (managed identity)  Yes — no secrets in code
```
