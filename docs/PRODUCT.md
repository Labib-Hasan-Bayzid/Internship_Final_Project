# Product Definition

## Customer problem

Dependency upgrades are frequently treated as metadata changes: a version number changes, CI runs, tests pass, and the upgrade is accepted. DCV adds a behavioral verification stage that compares the old and new versions under controlled execution.

## Decision model

DCV never asks an AI model to decide whether an upgrade should pass. The comparator receives measured evidence and project policy, then returns exactly one of PASS, REVIEW, or BLOCK.

AI is the explanation layer: it turns the evidence into a concise engineering narrative for a developer or reviewer.

## Commercial surface

1. Projects and repository mapping.
2. Policy configuration.
3. Manual verification.
4. PR-triggered verification through GitHub App/webhook.
5. GitHub Check result.
6. Verification history and evidence.
7. Rerun.
8. AI explanation.
9. CI/CD and GitOps deployment.

Billing, multi-tenancy, organization administration and enterprise control-plane features are implemented in this release. Full production security hardening—trusted authentication/SSO, stronger workload isolation, network policy, secrets management, abuse prevention and related controls—remains intentionally deferred.
