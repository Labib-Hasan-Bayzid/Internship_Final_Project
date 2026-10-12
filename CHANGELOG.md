# Changelog

## Local rollout reliability follow-up — 2026-10-12

- Added a backend startup probe so Kubernetes does not apply liveness restarts while the ASGI lifespan is initializing the database schema.
- Bounded background-worker shutdown and added named tasks plus diagnostics for workers that fail to stop promptly.
- Expanded failed rollout output to include Deployment, ReplicaSet, Pod, container log, PostgreSQL Pod, and event evidence; added a read-only `scripts/diagnose-local.ps1` utility.
- Made the Windows local deployment scripts resolve current image tags and expected-release markers from `VERSION` using disposable manifest copies.
- Removed duplicate apply-then-restart rollouts by stamping the Pod template once before apply; increased backend termination grace to 60 seconds and rollout wait bounds to 420 seconds.
- Documented the forensic interpretation and acceptance criteria for the reported `old replicas are pending termination` rollout failure.


## 15.0.0 — Final Consolidated Release — 2026-10-08

### Product capabilities
- Behavioral dependency verification with deterministic PASS / REVIEW / BLOCK decisions.
- Python and Node.js runners with Kubernetes Job execution and evidence collection.
- Runtime smoke testing, filesystem/process/network observations, dependency-tree deltas, registry metadata, and runtime regression gates.
- GitHub App installation lifecycle, signed webhooks, durable/idempotent event processing, automatic PR dependency detection, GitHub Checks, and PR summary comments.
- GitHub Actions CI, GHCR publication, immutable commit-SHA image tagging, SBOM/provenance generation, and GitOps production image pinning.
- Argo CD AppProject/Application declarations with automated sync, self-healing, bounded retry, prune controls, and GitOps paths.
- Evidence-grounded AI explanations with persisted status, bounded retries, and deterministic verification as the authority.
- Multi-tenant organizations, membership roles, invitations, usage metering, plan entitlements, enterprise administration, and audit logs.
- Stripe Checkout, subscription synchronization, Customer Portal, idempotent webhook handling, and failed-event replay.

### Release reliability
- Replaced fragile nested local Kustomize overlays with shallow repository-relative roots:
  - `infra/k8s/local` -> `../base`
  - `infra/k8s/production` -> `../base`
- Removed PostgreSQL from the application Kustomize trees so an existing data-bearing StatefulSet and PVC are never patched by application deployment.
- PostgreSQL Service and StatefulSet are managed separately; the local bootstrap creates the StatefulSet only when absent and preserves an existing one.
- Local bootstrap performs Kustomize render validation before application changes.
- Local bootstrap uses versioned images and verifies the deployed backend release identity and required admin route.
- Removed destructive/missing-image Docker cleanup behavior from the local build path.
- Added Windows PowerShell syntax validation to CI.
- Added release tests for Kustomize resource containment and deployment strategy consistency.

### Explicit production boundary
Full production security hardening remains intentionally outside this requested release: trusted authentication/SSO enforcement, hardened tenant isolation, stronger workload sandboxing/network policy, production secrets management, abuse controls, and related security architecture.
