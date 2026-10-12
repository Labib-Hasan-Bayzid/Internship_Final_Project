# Dependency Change Verification (DCV) 15.0

**Know what changed before it reaches production.**

DCV is a developer platform that verifies dependency changes by executing old and new versions in short-lived Kubernetes Jobs, collecting observable evidence, applying a deterministic gate, publishing CI-native results, and optionally generating an evidence-grounded AI explanation.

## Product scope in this release

- Next.js + TypeScript customer dashboard
- FastAPI control plane
- PostgreSQL persistence
- Docker images for frontend, backend and Python/Node runners
- Kubernetes verification Jobs
- deterministic PASS / REVIEW / BLOCK engine
- Python + Node.js dependency verification
- manifest and dependency-change parsing
- runtime smoke tests
- filesystem/process/network evidence
- GitHub App + signed webhooks + durable queue + PR discovery
- GitHub Checks + PR summary comments
- GitHub App installation lifecycle and tenant attachment
- GitHub Actions CI + GHCR publication + immutable image tags
- build provenance/SBOM workflow configuration
- Argo CD AppProject/Application manifests and GitOps image pinning
- OpenAI Responses API explanation layer with retries and explicit failure state
- organizations, members, roles, invitations, usage metering and audit logs
- Stripe Checkout + subscription state webhooks + Customer Portal
- plan entitlements and monthly limits
- production-oriented readiness/health endpoints

## Explicit boundary

The **full production security phase is intentionally excluded** as requested. That includes trusted authentication/SSO enforcement, strong tenant isolation controls, stronger sandbox isolation, network policy, secrets-management hardening, abuse controls and related security architecture.

The product code is tenant-aware, but the local development identity uses `X-Dcv-Actor-Email` and `X-Dcv-Organization-Id`. Put it behind a real identity provider and complete the security phase before exposing untrusted customer workloads.

## Architecture

```text
Developer / GitHub PR
        |
        v
     GitHub App ---- signed webhook ----> durable event queue
        |                                  |
        |                                  v
        |                           dependency diff
        |                                  |
        +-------------------------------> FastAPI
                                           |
                              +------------+------------+
                              |                         |
                              v                         v
                         PostgreSQL              Kubernetes Job
                                                        |
                                           +------------+------------+
                                           |                         |
                                      Python runner            Node runner
                                           |                         |
                                           +------------+------------+
                                                        |
                                                   evidence bundle
                                                        |
                                                        v
                                             deterministic comparator
                                                        |
                                          PASS / REVIEW / BLOCK
                                                /           \
                                               /             \
                                        GitHub Check          AI
                                                               |
                                                               v
                                                         explanation
```

## SaaS architecture

```text
Organization
  ├── Members / Roles
  ├── Projects
  ├── GitHub installations
  ├── Verification history
  ├── Usage period
  ├── Subscription
  └── Audit log
```

Plans are enforced by the backend before consuming metered resources. Stripe remains the billing system of record; PostgreSQL mirrors the active subscription state from signed Stripe webhooks.

## Local Windows start

Prerequisites: Windows 11, Docker Desktop, PowerShell, kind, kubectl.

```powershell
cd C:\dev\dependency-change-verification
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-local.ps1
```

Open:

```text
http://localhost:3000
```

For direct backend testing:

```powershell
kubectl port-forward svc/backend 8000:8000 -n dcv
```

## GitHub App

See `docs/GITHUB-APP.md` and `docs/github-app-manifest.json`.

The runtime validates `X-Hub-Signature-256`, persists `X-GitHub-Delivery` idempotency keys, processes PR events asynchronously, mints installation access tokens on demand, detects dependency changes from supported manifests, and publishes a Check Run for each detected dependency.

GitHub recommends HMAC-SHA256 webhook verification and installation access tokens are short-lived, so DCV does not persist installation tokens.

## GitHub Actions and Argo CD

- `.github/workflows/ci.yml`: PR/main CI, backend tests, frontend build, Kustomize validation, container-build validation.
- `.github/workflows/container.yml`: GHCR publication, immutable SHA tags, provenance/SBOM configuration, GitOps production image pinning.
- `.github/workflows/release.yml`: release validation and protected production environment entry point.
- `infra/k8s/argocd/`: Argo AppProject + local/production Applications.

Argo CD supports automated sync, pruning, self-healing and bounded retries through its Application specification.

GitHub Actions can also use OIDC for cloud workload identity rather than long-lived cloud credentials.

## AI

The AI layer is intentionally downstream of the deterministic decision:

```text
Evidence -> deterministic decision -> OpenAI explanation
```

AI cannot change PASS/REVIEW/BLOCK. The implementation uses the OpenAI Responses API with `store=false` and tracks queued/running/completed/failed explanation state. Provider failures do not alter the deterministic decision. It can be tested from **GitHub & AI** in the dashboard.

## Billing

See `docs/STRIPE.md` and `docs/SAAS.md`.

DCV uses Stripe Checkout for recurring subscription purchase, the Stripe-hosted Customer Portal for subscription/billing management, and signed webhooks to synchronize local state.

## Enterprise administration

The Administration screen provides:

- organization profile
- tenant switching
- member role/status management
- invitation creation/acceptance
- usage and plan limits
- audit history

The Billing screen provides:

- current subscription state
- metered usage
- plan limits
- Checkout links
- Customer Portal access

## Production external dependencies

A source archive cannot create resources in another company's accounts. Before production you must supply:

- public HTTPS domain
- GitHub App + installation
- OpenAI API credentials/model access
- Stripe account, products, recurring prices and webhook endpoint
- GitHub repository + GHCR access
- managed PostgreSQL
- Kubernetes cluster
- Argo CD
- identity provider/gateway

These are documented in `docs/EXTERNAL-INTEGRATIONS.md`.

## Product limitation

Observable behavior is evidence, not proof of maliciousness. DCV should not be marketed as a universal malware sandbox until the later security phase is implemented.
