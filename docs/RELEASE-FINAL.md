# DCV 15.0.0 — final consolidated functional release

This is the consolidated Dependency Change Verification release. It supersedes earlier 9.x/10.x local archives and is the baseline for future customer deployments.

## Local Windows + Docker Desktop + kind

From the repository root in Windows PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-local.ps1
```

The bootstrap is designed to be safe against an existing DCV PostgreSQL StatefulSet: application manifests are deployed through the local Kustomize root, while PostgreSQL is managed separately so an existing data-bearing StatefulSet is not patched and Kubernetes immutable-field errors are avoided.

The bootstrap validates Kustomize rendering before applying application resources, builds all four release-tagged images, loads them into all kind nodes, waits for PostgreSQL and application rollouts, and verifies the deployed backend release identity and required admin route.

## Functional scope

Core behavioral verification, Kubernetes Jobs, deterministic PASS/REVIEW/BLOCK decisions, Python and Node runners, GitHub App/webhook/checks integration, GitHub Actions CI, GHCR/SBOM/provenance workflows, Argo CD/GitOps configuration, AI explanation with retry/status handling, organizations/roles/invitations/usage/entitlements, Stripe checkout/subscription/portal/webhook handling, enterprise administration, and audit logging are included.

## Production boundary

Production deployment still requires customer-owned external infrastructure and credentials such as PostgreSQL, GitHub App credentials, OpenAI credentials, Stripe credentials, DNS/Ingress, and the customer's Kubernetes/Argo CD environment. Full production security hardening remains intentionally outside the requested scope.
